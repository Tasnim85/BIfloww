"""intake/column_types.py — Step 1a entrypoint: semantic column classification (Malek).

This is the COLUMN_TYPES step in the DAG.
It reads the uploaded tables, classifies every column using the taxonomy
and rule-based engine, and writes:
  runs/<run_id>/column_types/column_types.json  (ColumnTypesReport)

Step 1 (this file): taxonomy + rule-based classification.
Step 2 (future):    embedding-based classifier trained on Olist labels.
"""
from __future__ import annotations

import csv
from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import SemanticType, save
from contracts.intake import ColumnType, ColumnTypesReport
from intake.semantic_detection.src.taxonomy_loader import TaxonomyLoader

_LOADER = TaxonomyLoader()   # loaded once at import time

# Map taxonomy type_id → contracts.common.SemanticType
_TYPE_MAP: dict[str, SemanticType] = {
    "EMAIL":           SemanticType.EMAIL,
    "PHONE":           SemanticType.PHONE,
    "PERSON_NAME":     SemanticType.PERSON_NAME,
    "PERSON_ID":       SemanticType.ID,
    "AGE":             SemanticType.NUMBER,
    "BIRTH_DATE":      SemanticType.DATE,
    "PERSONAL_ADDRESS": SemanticType.TEXT,
    "PRICE":           SemanticType.AMOUNT,
    "PAYMENT_AMOUNT":  SemanticType.AMOUNT,
    "REVENUE":         SemanticType.AMOUNT,
    "COST":            SemanticType.AMOUNT,
    "DISCOUNT":        SemanticType.AMOUNT,
    "TAX":             SemanticType.AMOUNT,
    "FREIGHT_COST":    SemanticType.AMOUNT,
    "PROFIT":          SemanticType.AMOUNT,
    "DATE":            SemanticType.DATE,
    "DATETIME":        SemanticType.DATETIME,
    "TIME":            SemanticType.OTHER,
    "YEAR":            SemanticType.NUMBER,
    "MONTH":           SemanticType.NUMBER,
    "DURATION":        SemanticType.NUMBER,
    "PERIOD":          SemanticType.OTHER,
    "COUNTRY":         SemanticType.OTHER,
    "STATE":           SemanticType.STATE,
    "CITY":            SemanticType.CITY,
    "REGION":          SemanticType.OTHER,
    "POSTAL_CODE":     SemanticType.ZIP_CODE,
    "LATITUDE":        SemanticType.NUMBER,
    "LONGITUDE":       SemanticType.NUMBER,
    "ORDER_ID":        SemanticType.ID,
    "PRODUCT_ID":      SemanticType.ID,
    "SELLER_ID":       SemanticType.ID,
    "INVOICE_ID":      SemanticType.ID,
    "TRANSACTION_ID":  SemanticType.ID,
    "ORGANIZATION_ID": SemanticType.ID,
    "STATUS":          SemanticType.CATEGORY,
    "PRODUCT_CATEGORY": SemanticType.CATEGORY,
    "PAYMENT_METHOD":  SemanticType.CATEGORY,
    "CUSTOMER_SEGMENT": SemanticType.CATEGORY,
    "PRIORITY":        SemanticType.CATEGORY,
    "BOOLEAN_FLAG":    SemanticType.BOOLEAN,
    "QUANTITY":        SemanticType.QUANTITY,
    "COUNT":           SemanticType.QUANTITY,
    "WEIGHT":          SemanticType.NUMBER,
    "LENGTH":          SemanticType.NUMBER,
    "VOLUME":          SemanticType.NUMBER,
    "PERCENTAGE":      SemanticType.NUMBER,
    "RATE":            SemanticType.NUMBER,
    "RATING":          SemanticType.NUMBER,
    "NUMERIC_MEASURE": SemanticType.NUMBER,
    "DESCRIPTION":     SemanticType.TEXT,
    "COMMENT":         SemanticType.TEXT,
    "TITLE":           SemanticType.TEXT,
    "FREE_TEXT":       SemanticType.TEXT,
    "LABEL":           SemanticType.CATEGORY,
    "SYSTEM_ID":       SemanticType.ID,
    "HASH_VALUE":      SemanticType.OTHER,
    "VERSION":         SemanticType.OTHER,
    "FILE_REFERENCE":  SemanticType.OTHER,
    "UNKNOWN":         SemanticType.OTHER,
}

# Columns whose hint is HIGH or CRITICAL are flagged as pii_candidate
_PII_HINT_LEVELS = {"HIGH", "CRITICAL"}


def _classify_column(table: str, col: str) -> ColumnType:
    """Rule-based classification: alias lookup → UNKNOWN fallback."""
    type_id = _LOADER.type_id_from_alias(col.lower())
    if type_id is None:
        # Try partial keyword matching
        col_lower = col.lower()
        for alias, tid in {
            "id": "SYSTEM_ID", "date": "DATE", "time": "DATETIME",
            "amount": "PAYMENT_AMOUNT", "price": "PRICE", "status": "STATUS",
            "name": "PERSON_NAME", "email": "EMAIL", "phone": "PHONE",
            "city": "CITY", "state": "STATE", "zip": "POSTAL_CODE",
            "lat": "LATITUDE", "lng": "LONGITUDE", "score": "RATING",
            "value": "PAYMENT_AMOUNT", "qty": "QUANTITY",
        }.items():
            if alias in col_lower:
                type_id = tid
                break
        else:
            type_id = "UNKNOWN"

    semantic_type = _TYPE_MAP.get(type_id, SemanticType.OTHER)
    privacy_hint  = _LOADER.privacy_hint_for(type_id) or "LOW"
    confidence    = 0.85 if type_id != "UNKNOWN" else 0.0
    pii_candidate = privacy_hint in _PII_HINT_LEVELS

    return ColumnType(
        table=table,
        column=col,
        semantic_type=semantic_type,
        confidence=confidence,
        pii_candidate=pii_candidate,
    )


def _read_headers(csv_path: Path) -> list[str]:
    """Read only the header row of a CSV."""
    with open(csv_path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        return next(reader, [])


def run(ctx: RunContext) -> AgentResult:
    """Step 1a: classify every column of every uploaded table."""
    tables_dir: Path = ctx.inputs["tables"]

    if not tables_dir.exists():
        ctx.log("classify", "FAILED", evidence={"error": "tables/ folder not found"})
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.FAILED,
            message="Input tables/ folder not found.",
        )

    all_columns: list[ColumnType] = []
    csv_files = list(tables_dir.glob("*.csv"))

    for csv_path in csv_files:
        table_name = csv_path.stem
        try:
            headers = _read_headers(csv_path)
        except Exception as exc:
            ctx.log("read_headers", "FAILED",
                    inputs=[str(csv_path)], evidence={"error": str(exc)})
            continue

        for col in headers:
            all_columns.append(_classify_column(table_name, col))

    report = ColumnTypesReport(model="rules@1.0", columns=all_columns)
    out_path = ctx.output("report")
    save(report, out_path)

    pii_count = sum(1 for c in all_columns if c.pii_candidate)
    ctx.log(
        "classify", "SUCCESS",
        inputs=[str(tables_dir)],
        outputs=[str(out_path)],
        rule_version="column_types:rules@1.0",
        evidence={
            "tables": len(csv_files),
            "columns": len(all_columns),
            "pii_candidates": pii_count,
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"report": out_path},
        message=(f"Classified {len(all_columns)} columns across {len(csv_files)} table(s). "
                 f"{pii_count} PII candidate(s) flagged for Ikbel."),
    )
