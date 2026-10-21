"""Dataset-independent semantic PII classification by local Llama 3."""
import re
import hashlib
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, create_model

from bo2.local_llm import request_json

SemanticType = Literal["EMAIL", "PHONE", "PERSON_NAME", "PERSONAL_ID", "ADDRESS", "POSTAL_CODE", "COORDINATE", "BIRTH_DATE", "AGE", "SENSITIVE_ATTRIBUTE", "FREE_TEXT", "INTERNAL_KEY", "TIMESTAMP", "MEASURE", "CATEGORY", "UNKNOWN"]
SENSITIVE = {"EMAIL", "PHONE", "PERSON_NAME", "PERSONAL_ID", "ADDRESS", "POSTAL_CODE", "COORDINATE", "BIRTH_DATE", "AGE", "SENSITIVE_ATTRIBUTE", "FREE_TEXT"}
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
PHONE = re.compile(r"(?<!\w)(?:\+\d[\d ().-]{6,}\d|\d{2,4}[ ().-]\d{2,4}[ ().-]\d{2,4})(?!\w)")
ISO_DATE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}(?:[ T].*)?$|^\d{2}[-/]\d{2}[-/]\d{4}$")
HEARTBEAT_SECONDS = 15
PROMPT_VERSION = "pii-column-types-en@2.6"
PROMPT_PATH = Path(__file__).parent / "prompts" / "classify_columns_en.txt"
KEY_PROMPT_PATH = PROMPT_PATH.with_name("classify_keys_en.txt")
REVIEW_PROMPT_PATH = PROMPT_PATH.with_name("review_attribute_en.txt")


def prompt_metadata():
    return {"prompt_version": PROMPT_VERSION, "prompt_sha256": hashlib.sha256(PROMPT_PATH.read_bytes() + b'\n---KEY-SCOPE---\n' + KEY_PROMPT_PATH.read_bytes() + b'\n---ATTRIBUTE-REVIEW---\n' + REVIEW_PROMPT_PATH.read_bytes()).hexdigest()}


def request_with_progress(prompt, metadata, schema, model, progress=None):
    if progress is None:
        return request_json(prompt, metadata, schema, model)
    finished = Event()
    started = monotonic()

    def heartbeat():
        while not finished.wait(HEARTBEAT_SECONDS):
            progress(f"Attente de Llama 3 : {int(monotonic() - started)} s pour ce lot...")

    worker = Thread(target=heartbeat, name="pii-llama-heartbeat", daemon=True)
    worker.start()
    try:
        return request_json(prompt, metadata, schema, model)
    finally:
        finished.set()
        worker.join(timeout=1)


class ColumnPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_type: SemanticType
    confidence: float = Field(ge=0, le=1)


def signals(series):
    text = series.dropna().astype(str)
    if text.empty:
        return {"email_count": 0, "phone_count": 0, "email_full_count": 0, "phone_full_count": 0}
    email = text.str.contains(EMAIL)
    phone = text.str.contains(PHONE) & ~text.str.match(ISO_DATE)
    return {"email_count": int(email.sum()), "phone_count": int(phone.sum()), "email_full_count": int(text.str.fullmatch(EMAIL).sum()), "phone_full_count": int((text.str.fullmatch(PHONE) & ~text.str.match(ISO_DATE)).sum())}


def classify_columns(tables: dict[str, pd.DataFrame], hints=None, model=None, batch_size=4, progress=None, confidence_threshold=0.75):
    """Send bounded samples to loopback only. Never persist samples or raw answers."""
    if not 1 <= batch_size <= 12:
        raise ValueError("PII batch_size must be between 1 and 12")
    hints = hints or {}
    descriptors = []
    if progress:
        progress("Preparation des statistiques et des exemples locaux...")
    for table, frame in tables.items():
        for column in frame:
            values = frame[column].dropna().astype(str)
            distinct = values.drop_duplicates()
            positions = sorted({0, len(distinct) // 2, len(distinct) - 1}) if len(distinct) else []
            examples = [distinct.iloc[index][:80] for index in positions]
            hint = hints.get(table, {}).get(column) if isinstance(hints.get(table, {}), dict) else None
            descriptors.append((table, column, {"table": table, "column": column, "rows": len(frame), "missing": int(frame[column].isna().sum()), "distinct": len(distinct), "dtype": str(frame[column].dtype), "content_signals": signals(frame[column]), "examples_local_only": examples, "upstream_hint": hint}))
    result = {table: {} for table in tables}
    # Keep a table's semantic context together and bound the prompt/schema size.
    batches = []
    for table in tables:
        table_columns = [item for item in descriptors if item[0] == table]
        batches.extend(table_columns[start:start + batch_size] for start in range(0, len(table_columns), batch_size))
    total_batches = len(batches)
    if progress:
        progress(f"{len(tables)} table(s), {len(descriptors)} colonne(s), {total_batches} lot(s) a analyser.")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    for number, batch in enumerate(batches, start=1):
        active_tables = {table for table, _, _ in batch}
        context = {table: [name[:80] for name in tables[table].columns[:16]] for table in active_tables}
        schema = create_model("PiiColumnBatch", __config__=ConfigDict(extra="forbid"), **{f"c{index}": (ColumnPrediction, ...) for index in range(len(batch))})
        metadata = {"table_context": context, "columns": {f"c{index}": descriptor for index, (_, _, descriptor) in enumerate(batch)}}
        started = monotonic()
        if progress:
            progress(f"Lot {number}/{total_batches} : analyse de {len(batch)} colonne(s) par Llama 3...")
        response = request_with_progress(prompt, metadata, schema, model, progress)
        for index, (table, column, _) in enumerate(batch):
            result[table][column] = ColumnPrediction.model_validate(getattr(response, f"c{index}"))
        if progress:
            progress(f"Lot {number}/{total_batches} termine en {monotonic() - started:.1f} s.")
    result = review_uncertain_attributes(tables, descriptors, result, model, progress, confidence_threshold)
    return refine_key_entities(tables, result, model, progress)


def review_uncertain_attributes(tables, descriptors, predictions, model=None, progress=None, confidence_threshold=0.75):
    """Reassess uncertain business attributes individually, without forcing a keep."""
    prompt = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    for table, column, descriptor in descriptors:
        initial = predictions[table][column]
        if initial.semantic_type not in {"CATEGORY", "MEASURE", "TIMESTAMP"} or initial.confidence >= confidence_threshold:
            continue
        schema = create_model("PiiAttributeReview", __config__=ConfigDict(extra="forbid"), c0=(ColumnPrediction, ...))
        metadata = {"table_context": {table: list(tables[table].columns[:16])}, "columns": {"c0": descriptor}}
        if progress:
            progress(f"Verification individuelle de l'attribut incertain : {table}.{column}...")
        response = request_with_progress(prompt, metadata, schema, model, progress)
        predictions[table][column] = ColumnPrediction.model_validate(response.c0)
    return predictions


class KeyPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_type: Literal["PERSONAL_ID", "INTERNAL_KEY", "UNKNOWN"]
    confidence: float = Field(ge=0, le=1)


def refine_key_entities(tables, predictions, model=None, progress=None):
    """Ask a focused semantic question across references before masking any key."""
    groups = {}
    for table, columns in predictions.items():
        for column, prediction in columns.items():
            if prediction.semantic_type in {"PERSONAL_ID", "INTERNAL_KEY"}:
                groups.setdefault(column.casefold(), []).append((table, column))
    entries = list(groups.items())
    prompt = KEY_PROMPT_PATH.read_text(encoding="utf-8")
    for start in range(len(entries)):
        batch = entries[start:start + 1]
        schema = create_model("PiiKeyEntityBatch", __config__=ConfigDict(extra="forbid"), **{f"c{i}": (KeyPrediction, ...) for i in range(len(batch))})
        metadata = {"keys": {f"c{i}": {"column": name, "occurrences": [{"table": table, "column": column, "table_columns": list(tables[table].columns[:16])} for table, column in occurrences]} for i, (name, occurrences) in enumerate(batch)}}
        if progress:
            progress(f"Verification semantique des cles : lot {start + 1}/{len(entries)}...")
        response = request_with_progress(prompt, metadata, schema, model, progress)
        for i, (_, occurrences) in enumerate(batch):
            revised = ColumnPrediction.model_validate(getattr(response, f"c{i}").model_dump())
            if revised.semantic_type == "UNKNOWN":
                # An unresolved key must pause even in conservative redaction mode.
                revised = ColumnPrediction(semantic_type="INTERNAL_KEY", confidence=0)
            for table, column in occurrences:
                predictions[table][column] = revised.model_copy()
    return predictions


def enforce_contact_signals(series, prediction):
    """Scan every row for explicit contacts; supplement, never replace, the LLM."""
    counts = signals(series)
    if not any(counts.values()):
        return prediction, "llm"
    non_null = int(series.notna().sum())
    if counts["email_full_count"] >= max(1, non_null * 0.8):
        kind = "EMAIL"
    elif counts["phone_full_count"] >= max(1, non_null * 0.8):
        kind = "PHONE"
    else:
        kind = "FREE_TEXT"
    return ColumnPrediction(semantic_type=kind, confidence=1), "contact_guardrail"
