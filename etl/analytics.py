"""Analytical views published in the shared manifest (contracts v1.1).

The dimensional build keeps its own technical tables (__bi_row_id, __bi_fk_...).
The Analyst (Rabeb) only reads the shared manifest, and joins a fact to a dimension
when the fact has a column with the SAME name as the dimension's one-column primary key.
These views give it that shape, for any dataset:

- fact view  = the fact's own columns + the columns of every parent it reaches
               (many-to-one, so no row is multiplied) + its dates typed as DATE;
- dim view   = the dimension's own columns + the columns of a reference table that
               translates one of them (e.g. product_category_name -> English name);
- dim_date   = the calendar, keyed by `date` (DATE), grain "day", with `year_month`.

View names and grains: those agreed in contracts/examples (README section 9) for the files listed
in etl/view_names.yaml; any other dataset gets generic ones (fact_<file>, dim_<file>).
"""
import re
from pathlib import Path

import pandas as pd
import yaml

from .generic import quote

SK_PREFIX = "__bi_"
NAMES_FILE = Path(__file__).with_name("view_names.yaml")


def singular(word):
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def short_names(metadata):
    """Readable, stable names: drop the prefix/suffix shared by most files (olist_..._dataset)."""
    tokens = {t: re.sub(r"[^a-z0-9]+", "_", info["source"].lower()).strip("_").split("_")
              for t, info in metadata.items()}
    half = len(tokens) / 2
    firsts = pd.Series([v[0] for v in tokens.values() if len(v) > 1]).value_counts()
    lasts = pd.Series([v[-1] for v in tokens.values() if len(v) > 1]).value_counts()
    prefix = firsts.index[0] if len(firsts) and firsts.iloc[0] >= half else None
    suffix = lasts.index[0] if len(lasts) and lasts.iloc[0] >= half else None
    result = {}
    for table, words in tokens.items():
        if prefix and len(words) > 1 and words[0] == prefix:
            words = words[1:]
        if suffix and len(words) > 1 and words[-1] == suffix:
            words = words[:-1]
        result[table] = "_".join(words) or table
    return result


def date_name(column, taken):
    if "timestamp" in column:
        name = column.replace("timestamp", "date")
    elif column.endswith("date"):
        name = column + "_day"
    else:
        name = column + "_date"
    if name == column or name in taken:
        name = column + "_day"
    return name


def bare_name(name):
    """olist_order_payments_dataset -> order_payments (the name the PII step publishes)."""
    return re.sub(r"^olist_|_dataset$", "", str(name).lower())


def agreed_view(agreed, source):
    """The agreed view name/grain for a source table, whatever spelling of the file reached the ETL:
    the PII step renames olist_order_payments_dataset.csv to order_payments."""
    if source in agreed:
        return agreed[source]
    return next((v for k, v in agreed.items() if bare_name(k) == bare_name(source)), {})


def build_views(connection, frames, metadata, roles, names, links, date_specs, reachable, names_file=NAMES_FILE):
    """Create the views; return (tables for the shared manifest, their receipts)."""
    short = short_names(metadata)
    agreed = yaml.safe_load(Path(names_file).read_text(encoding="utf-8")) or {} if Path(names_file).is_file() else {}
    config = {t: agreed_view(agreed, metadata[t]["source"]) for t in metadata}
    existing = {r[0] for r in connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
    used = set()

    def free(table, prefix):
        name = config[table].get("name")
        if name and (name in existing or name in used):
            raise ValueError(f"View name {name} of view_names.yaml is already used")
        name = name or prefix + short[table]
        if name in existing or name in used:
            name += "_view"
        used.add(name)
        return name

    def grain(table):
        return config[table].get("grain") or singular(short[table])

    def key(table):
        return config[table].get("primary_key") or metadata[table]["primary_key"]

    def original(table):
        return [c for c in frames[table].columns if not c.startswith(SK_PREFIX)]

    def count(view):
        return connection.execute(f"SELECT count(*) FROM {quote(view)}").fetchone()[0]

    tables, receipts, view_of = [], [], {}

    # 1. Dimensions, with the columns of a reference table that translates one of their columns.
    for table, role in roles.items():
        if role.role != "dimension":
            continue
        view = free(table, "dim_")
        select = [f"d.{quote(c)}" for c in original(table)]
        sources = {c: f"{metadata[table]['source']}.{c}" for c in original(table)}
        joins, n = [], 0
        for ref, ref_role in roles.items():
            if ref_role.role != "reference":
                continue
            for column in original(table):
                if column not in frames[ref] or frames[ref][column].isna().any() or frames[ref][column].duplicated().any():
                    continue
                n += 1
                joins.append(f"LEFT JOIN {quote(names[ref])} r{n} ON d.{quote(column)} = r{n}.{quote(column)}")
                for extra in original(ref):
                    if extra not in sources:
                        select.append(f"r{n}.{quote(extra)}")
                        sources[extra] = f"{metadata[ref]['source']}.{extra}"
                break
        connection.execute(f"CREATE VIEW {quote(view)} AS SELECT {', '.join(select)} "
                           f"FROM {quote(names[table])} d " + " ".join(joins))
        rows = count(view)
        if rows != len(frames[table]):
            raise ValueError(f"Reference join multiplied rows of {view}")
        tables.append({"name": view, "kind": "dimension", "grain": grain(table), "primary_key": key(table),
                       "row_count": rows, "columns": list(sources)})
        receipts.append({"output_table": view, "source_tables": list(dict.fromkeys(s.split(".")[0] for s in sources.values())),
                         "join_keys": [], "rows_before": len(frames[table]), "rows_after": rows,
                         "grain": grain(table), "filters": [], "column_sources": sources})
        view_of[table] = view

    # 2. Calendar: key `date`, grain "day" (what the Analyst's compiler looks for).
    if "dim_calendar" in existing:
        view = "dim_date"
        if view in existing:
            raise ValueError("dim_date already exists")
        connection.execute(f"CREATE VIEW {quote(view)} AS SELECT CAST(date AS DATE) AS date, year, month, day, "
                           "strftime(CAST(date AS DATE), '%Y-%m') AS year_month, dayname(CAST(date AS DATE)) AS weekday "
                           "FROM dim_calendar")
        rows = count(view)
        cols = ["date", "year", "month", "day", "year_month", "weekday"]
        tables.append({"name": view, "kind": "dimension", "grain": "day", "primary_key": ["date"],
                       "row_count": rows, "columns": cols})
        receipts.append({"output_table": view, "source_tables": ["dim_calendar"], "join_keys": [],
                         "rows_before": rows, "rows_after": rows, "grain": "day", "filters": [],
                         "column_sources": {c: "dim_calendar." + ("date" if c in ("year_month", "weekday") else c) for c in cols}})

    # 3. Facts, flattened with their parents (many-to-one: the row count must not change).
    for table, role in roles.items():
        if role.role != "fact":
            continue
        view = free(table, "fact_")
        alias = {table: "f"}
        select = [f"f.{quote(c)}" for c in original(table)]
        sources = {c: f"{metadata[table]['source']}.{c}" for c in original(table)}
        joins, join_keys = [], []
        for parent, path in reachable(table, links).items():
            if roles[parent].role == "unresolved":
                continue
            edge = path[-1]
            if edge["child"] not in alias:
                continue
            alias[parent] = f"p{len(alias)}"
            on = " AND ".join(f"{alias[edge['child']]}.{quote(c)} = {alias[parent]}.{quote(c)}" for c in edge["columns"])
            joins.append(f"LEFT JOIN {quote(names[parent])} {alias[parent]} ON {on}")
            join_keys.extend(edge["columns"])
            for column in original(parent):
                if column not in sources:
                    select.append(f"{alias[parent]}.{quote(column)}")
                    sources[column] = f"{metadata[parent]['source']}.{column}"
        # Every date as DATE. The main date is the event's own date: dates of descriptive tables
        # (a birth date in patients) are kept only when there is no other; then the earliest one wins
        # (the purchase comes before the shipping limit). view_names.yaml can name it (date_from).
        specs = [s for s in date_specs.get(table, []) if s[0] in alias]
        events = [s for s in specs if roles[s[0]].role != "dimension"] or specs
        median = lambda s: pd.to_datetime(frames[s[0]][s[1]], errors="coerce", format="mixed", utc=True).median()
        main = next((s for s in specs if s[1] == config[table].get("date_from")), None) or \
            (min(events, key=median) if events else None)
        date_columns, main_date = [], None
        for spec in specs:
            owner, column, _ = spec
            name = date_name(column, sources)
            if name in sources:
                continue
            select.append(f"CAST(TRY_CAST({alias[owner]}.{quote(column)} AS TIMESTAMP) AS DATE) AS {quote(name)}")
            sources[name] = f"{metadata[owner]['source']}.{column}"
            date_columns.append(name)
            if spec == main:
                main_date = name
        connection.execute(f"CREATE VIEW {quote(view)} AS SELECT {', '.join(select)} "
                           f"FROM {quote(names[table])} f " + " ".join(joins))
        rows = count(view)
        if rows != len(frames[table]):
            raise ValueError(f"Parent join multiplied rows of {view}")
        low = high = None
        if main_date:
            low, high = connection.execute(f"SELECT min({quote(main_date)}), max({quote(main_date)}) FROM {quote(view)}").fetchone()
        tables.append({"name": view, "kind": "fact", "grain": grain(table), "primary_key": key(table),
                       "row_count": rows, "columns": list(sources), "date_column": main_date,
                       "date_min": str(low) if low else None, "date_max": str(high) if high else None})
        receipts.append({"output_table": view, "source_tables": list(dict.fromkeys(s.split(".")[0] for s in sources.values())),
                         "join_keys": list(dict.fromkeys(join_keys)), "rows_before": len(frames[table]), "rows_after": rows,
                         "grain": grain(table), "filters": [], "column_sources": sources})
    return tables, receipts
