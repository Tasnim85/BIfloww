"""Choose the profiling settings for ANY dataset when nobody gave them.

Order of priority, for coverage and for anomalies:
1. the settings given in ctx.params (the Streamlit page passes them);
2. the Olist defaults, when the Olist table and columns are there (as in contracts/examples);
3. a choice made from the data itself, explained in the returned "reason".

Only column contents and name words are used: no table or column name is required.
"""
import re
import unicodedata

import pandas as pd

OLIST_COVERAGE = {"orders_table": "orders", "date_column": "order_purchase_timestamp",
                  "status_column": "order_status", "order_id_column": "order_id"}
OLIST_ANOMALIES = {"anomaly_table": "order_payments", "anomaly_id_column": "order_id", "amount_column": "payment_value"}

KEY_WORDS = {"id", "ids", "identifier", "identifiant", "key", "code", "ref", "reference", "uuid", "guid",
             "num", "no", "nr", "numero", "nummer", "cle", "zip", "postal", "cep", "prefix", "sequential", "seq"}
STATUS_WORDS = {"status", "statut", "state", "etat", "estado", "stato", "stage", "etape"}
PROTECTED = {"PERSONAL_ID", "INTERNAL_KEY", "BUSINESS_KEY", "POSTAL_CODE"}


def words(column):
    plain = unicodedata.normalize("NFKD", str(column)).encode("ascii", "ignore").decode()
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", plain)
    return set(w for w in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if w)


def is_key(column):
    return bool(KEY_WORDS & words(column))


def date_columns(frame):
    """Columns whose filled values are ALL dates (real dates, or text such as '2018-08-01 10:00')."""
    found = []
    for column in frame:
        series = frame[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            found.append(column)
            continue
        if not (pd.api.types.is_string_dtype(series) or series.dtype == object):
            continue
        sample = series.dropna().astype(str).head(500)
        if sample.empty or not sample.str.contains(r"\d{2,4}[-/.]\d{1,2}[-/.]\d{1,4}").all():
            continue
        if pd.to_datetime(sample, errors="coerce", format="mixed").notna().all():
            found.append(column)
    return found


def unique_id(frame):
    """A single identifier column that is complete and unique, or None."""
    for column in frame:
        if is_key(column) and not pd.api.types.is_float_dtype(frame[column]) \
                and frame[column].notna().all() and not frame[column].duplicated().any():
            return column
    return None


def status_column(frame, exclude):
    """A short list of text values describing the state of a row (delivered, canceled...)."""
    candidates = []
    for column in frame:
        series = frame[column]
        if column in exclude or is_key(column) or not (pd.api.types.is_string_dtype(series) or series.dtype == object):
            continue
        distinct = series.nunique(dropna=True)
        if 2 <= distinct <= 20 and distinct < len(frame) / 2:
            candidates.append((not (STATUS_WORDS & words(column)), distinct, column))
    return min(candidates)[2] if candidates else None


def coverage_settings(frames, params):
    """(table, date, status, id, reason) for the coverage profile."""
    if "orders_table" in params:
        return (params["orders_table"], params.get("date_column"), params.get("status_column"),
                params.get("order_id_column"), "settings given")
    olist = OLIST_COVERAGE
    if olist["orders_table"] in frames and {olist["date_column"], olist["status_column"], olist["order_id_column"]} <= set(frames[olist["orders_table"]]):
        return (olist["orders_table"], olist["date_column"], olist["status_column"], olist["order_id_column"],
                "Olist default (contracts/examples)")
    best = None
    for table, frame in frames.items():
        dates = date_columns(frame)
        if not dates or frame.empty:
            continue
        # The creation date of a row comes first: purchase before approval, delivery, review...
        filled = [d for d in dates if frame[d].notna().mean() >= 0.95] or dates
        date = min(filled, key=lambda d: pd.to_datetime(frame[d], errors="coerce", format="mixed", utc=True).median())
        identifier = unique_id(frame)
        status = status_column(frame, {date})
        score = (identifier is not None, status is not None, len(frame))
        if best is None or score > best[0]:
            best = (score, table, date, status, identifier)
    if best is None:
        raise ValueError("COVERAGE_TABLE: no table has a date column; coverage needs one")
    _, table, date, status, identifier = best
    return table, date, status, identifier, (f"auto: '{table}' has a unique identifier ({identifier}), a status ({status}) "
                                             f"and its earliest date column ({date})")


def anomaly_settings(frames, params, decisions):
    """(table, features, id, amount, reason) for the anomaly detection."""
    if "anomaly_table" in params:
        return (params["anomaly_table"], params.get("features"), params.get("anomaly_id_column", "order_id"),
                params.get("amount_column", "payment_value"), "settings given")
    olist = OLIST_ANOMALIES
    if olist["anomaly_table"] in frames and olist["amount_column"] in frames[olist["anomaly_table"]]:
        return olist["anomaly_table"], params.get("features"), olist["anomaly_id_column"], olist["amount_column"], \
            "Olist default (contracts/examples)"
    best = None
    for table, frame in frames.items():
        blocked = {d.get("column") for d in decisions if d.get("table") == table and
                   (d.get("action") != "keep" or d.get("semantic_type") in PROTECTED)}
        features = [c for c in frame if c not in blocked and not is_key(c) and not pd.api.types.is_bool_dtype(frame[c])
                    and pd.api.types.is_numeric_dtype(frame[c]) and frame[c].nunique() > 2][:20]
        if not features or len(frame) < 2:
            continue
        score = (len(features), len(frame))
        if best is None or score > best[0]:
            best = (score, table, features, unique_id(frame))
    if best is None:
        raise ValueError("ANOMALY_TABLE: no table has numeric measures to inspect")
    _, table, features, identifier = best
    # No amount column is assumed: a negative value is not an error in every dataset.
    return table, features, identifier, None, f"auto: '{table}' has the most numeric measures ({', '.join(features)})"
