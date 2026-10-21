"""intake/column_types.py — Step 1a entrypoint: rule-based semantic column classification.

Owner : Malek (BO1-06 / Step 1a)
Output: contracts.intake.ColumnTypesReport  (ColumnType per column)
Model : rules@1.1  (alias-exact → token-key → partial-token → OTHER)

Confidence scale (heuristic, NOT probabilities):
  0.90 — alias exact match in taxonomy
  0.75 — all key tokens recognised
  0.50 — at least one meaningful token matched
  0.00 — no match → OTHER

PII candidate rule (single authoritative definition):
  True if semantic_type in {EMAIL, PHONE, PERSON_NAME, ID*} AND personal-scope token
  OR semantic_type in {TEXT} AND free-text personal columns (COMMENT, DESCRIPTION)
  Concretely: column is pii_candidate when its resolved taxonomy type_id is in
  _PII_TAXONOMY_TYPES (see constant below).

NOTE: this file does NOT implement masking, hashing or PII decisions.
Those belong to Ikbel (privacy/).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import SemanticType, save
from contracts.intake import ColumnType, ColumnTypesReport
from contracts.proposals.semantic_contracts import (
    ClassificationStatus,
    PrivacyHint,
    SemanticColumn,
    SemanticMetadata,
)
from intake.semantic_detection.src.taxonomy_loader import TaxonomyLoader
from intake.semantic_detection.step2.schema_reader import ColumnSchema, TableSchema
from intake.semantic_detection.step3.hybrid_classifier import HybridClassifier


_LOADER = TaxonomyLoader()   # loaded once at import time

# ── Taxonomy type_id → contracts.common.SemanticType (17 values) ─────────
_TYPE_MAP: dict[str, SemanticType] = {
    "EMAIL":             SemanticType.EMAIL,
    "PHONE":             SemanticType.PHONE,
    "PERSON_NAME":       SemanticType.PERSON_NAME,
    "PERSON_ID":         SemanticType.ID,
    "AGE":               SemanticType.NUMBER,
    "BIRTH_DATE":        SemanticType.DATE,
    "PERSONAL_ADDRESS":  SemanticType.TEXT,
    "PRICE":             SemanticType.AMOUNT,
    "PAYMENT_AMOUNT":    SemanticType.AMOUNT,
    "REVENUE":           SemanticType.AMOUNT,
    "COST":              SemanticType.AMOUNT,
    "DISCOUNT":          SemanticType.AMOUNT,
    "TAX":               SemanticType.AMOUNT,
    "FREIGHT_COST":      SemanticType.AMOUNT,
    "PROFIT":            SemanticType.AMOUNT,
    "DATE":              SemanticType.DATE,
    "DATETIME":          SemanticType.DATETIME,
    "TIME":              SemanticType.OTHER,
    "YEAR":              SemanticType.NUMBER,
    "MONTH":             SemanticType.NUMBER,
    "DURATION":          SemanticType.NUMBER,
    "PERIOD":            SemanticType.OTHER,
    "COUNTRY":           SemanticType.OTHER,
    "STATE":             SemanticType.STATE,
    "CITY":              SemanticType.CITY,
    "REGION":            SemanticType.OTHER,
    "POSTAL_CODE":       SemanticType.ZIP_CODE,
    "LATITUDE":          SemanticType.NUMBER,
    "LONGITUDE":         SemanticType.NUMBER,
    "ORDER_ID":          SemanticType.ID,
    "PRODUCT_ID":        SemanticType.ID,
    "SELLER_ID":         SemanticType.ID,
    "INVOICE_ID":        SemanticType.ID,
    "TRANSACTION_ID":    SemanticType.ID,
    "ORGANIZATION_ID":   SemanticType.ID,
    "STATUS":            SemanticType.CATEGORY,
    "PRODUCT_CATEGORY":  SemanticType.CATEGORY,
    "PAYMENT_METHOD":    SemanticType.CATEGORY,
    "CUSTOMER_SEGMENT":  SemanticType.CATEGORY,
    "PRIORITY":          SemanticType.CATEGORY,
    "BOOLEAN_FLAG":      SemanticType.BOOLEAN,
    "QUANTITY":          SemanticType.QUANTITY,
    "COUNT":             SemanticType.QUANTITY,
    "WEIGHT":            SemanticType.NUMBER,
    "LENGTH":            SemanticType.NUMBER,
    "VOLUME":            SemanticType.NUMBER,
    "PERCENTAGE":        SemanticType.NUMBER,
    "RATE":              SemanticType.NUMBER,
    "RATING":            SemanticType.NUMBER,
    "NUMERIC_MEASURE":   SemanticType.NUMBER,
    "DESCRIPTION":       SemanticType.TEXT,
    "COMMENT":           SemanticType.TEXT,
    "TITLE":             SemanticType.TEXT,
    "FREE_TEXT":         SemanticType.TEXT,
    "LABEL":             SemanticType.CATEGORY,
    "SYSTEM_ID":         SemanticType.ID,
    "HASH_VALUE":        SemanticType.OTHER,
    "VERSION":           SemanticType.OTHER,
    "FILE_REFERENCE":    SemanticType.OTHER,
    "UNKNOWN":           SemanticType.OTHER,
}

# ── Taxonomy type_ids that make a column pii_candidate=True ──────────────
_PII_TAXONOMY_TYPES: frozenset[str] = frozenset({
    # Direct personal identifiers
    "EMAIL", "PHONE", "PERSON_NAME", "PERSON_ID",
    "BIRTH_DATE", "AGE", "PERSONAL_ADDRESS", "NATIONAL_ID",
    "POSTAL_CODE",       # partial address — Ikbel decides
    # Free-text columns may embed personal data
    "COMMENT", "FREE_TEXT", "DESCRIPTION",
})

# ── Additional alias table for Olist columns not yet in taxonomy YAML ────
_EXTRA_ALIASES: dict[str, tuple[str, float]] = {
    # (type_id, confidence)
    "customer_unique_id":           ("PERSON_ID",       0.90),
    "order_item_id":                ("ORDER_ID",          0.90),   # line number in an order, treated as a business ID
    "payment_installments":         ("QUANTITY",         0.90),
    "payment_sequential":           ("NUMERIC_MEASURE",  0.90),   # sequential number, maps to NUMBER
    "shipping_limit_date":          ("DATE",             0.90),
    "order_delivered_customer_date":("DATE",             0.90),
    "order_delivered_carrier_date": ("DATE",             0.90),
    "order_approved_at":            ("DATETIME",         0.90),
    "order_estimated_delivery_date":("DATE",             0.90),
    "review_id":                    ("SYSTEM_ID",        0.90),
    "review_score":                 ("RATING",           0.90),
    "review_comment_title":         ("COMMENT",          0.90),
    "review_comment_message":       ("COMMENT",          0.90),
    "review_creation_date":         ("DATE",             0.90),
    "review_answer_timestamp":      ("DATETIME",         0.90),
    "product_photos_qty":           ("QUANTITY",         0.90),
    "product_name_lenght":          ("NUMERIC_MEASURE",  0.75),
    "product_description_lenght":   ("NUMERIC_MEASURE",  0.75),
    "product_category_name_english":("PRODUCT_CATEGORY", 0.90),
    "geolocation_lat":              ("LATITUDE",         0.90),
    "geolocation_lng":              ("LONGITUDE",        0.90),
    "geolocation_city":             ("CITY",             0.90),
    "geolocation_state":            ("STATE",            0.90),
    "geolocation_zip_code_prefix":  ("POSTAL_CODE",      0.90),
    "seller_zip_code_prefix":       ("POSTAL_CODE",      0.90),
    "seller_city":                  ("CITY",             0.90),
    "seller_state":                 ("STATE",            0.90),
    "customer_zip_code_prefix":     ("POSTAL_CODE",      0.90),
}

# ── Token-based fallback rules ───────────────────────────────────────────
# Maps a WHOLE TOKEN to (type_id, confidence).
# "id" only matches when it is a complete token (not a substring).
_TOKEN_RULES: list[tuple[str, str, float]] = [
    ("email",       "EMAIL",            0.75),
    ("phone",       "PHONE",            0.75),
    ("mobile",      "PHONE",            0.75),
    ("tel",         "PHONE",            0.75),
    ("timestamp",   "DATETIME",         0.75),
    ("datetime",    "DATETIME",         0.75),
    ("date",        "DATE",             0.75),
    ("time",        "TIME",             0.50),
    ("year",        "YEAR",             0.75),
    ("month",       "MONTH",            0.75),
    ("amount",      "PAYMENT_AMOUNT",   0.75),
    ("value",       "PAYMENT_AMOUNT",   0.50),
    ("price",       "PRICE",            0.75),
    ("cost",        "COST",             0.75),
    ("freight",     "FREIGHT_COST",     0.75),
    ("revenue",     "REVENUE",          0.75),
    ("profit",      "PROFIT",           0.75),
    ("discount",    "DISCOUNT",         0.75),
    ("tax",         "TAX",              0.75),
    ("status",      "STATUS",           0.75),
    ("type",        "STATUS",           0.50),
    ("category",    "PRODUCT_CATEGORY", 0.75),
    ("segment",     "CUSTOMER_SEGMENT", 0.50),
    ("city",        "CITY",             0.75),
    ("state",       "STATE",            0.75),
    ("country",     "COUNTRY",          0.75),
    ("region",      "REGION",           0.75),
    ("zip",         "POSTAL_CODE",      0.75),
    ("postal",      "POSTAL_CODE",      0.75),
    ("lat",         "LATITUDE",         0.75),
    ("lng",         "LONGITUDE",        0.75),
    ("lon",         "LONGITUDE",        0.75),
    ("latitude",    "LATITUDE",         0.75),
    ("longitude",   "LONGITUDE",        0.75),
    ("score",       "RATING",           0.50),
    ("rating",      "RATING",           0.75),
    ("qty",         "QUANTITY",         0.75),
    ("quantity",    "QUANTITY",         0.75),
    ("count",       "COUNT",            0.75),
    ("weight",      "WEIGHT",           0.75),
    ("length",      "LENGTH",           0.75),
    ("height",      "LENGTH",           0.50),
    ("width",       "LENGTH",           0.50),
    ("description", "DESCRIPTION",      0.75),
    ("comment",     "COMMENT",          0.75),
    ("message",     "COMMENT",          0.50),
    ("title",       "TITLE",            0.75),
    ("name",        "PERSON_NAME",      0.50),
    ("age",         "AGE",              0.75),
    ("birth",       "BIRTH_DATE",       0.75),
    ("address",     "PERSONAL_ADDRESS", 0.75),
    ("street",      "PERSONAL_ADDRESS", 0.75),
    ("installment", "QUANTITY",         0.75),
    ("sequential",  "NUMERIC_MEASURE",  0.50),
    ("photos",      "QUANTITY",         0.75),
    ("flag",        "BOOLEAN_FLAG",     0.75),
    ("active",      "BOOLEAN_FLAG",     0.50),
    ("enabled",     "BOOLEAN_FLAG",     0.50),
    ("hash",        "HASH_VALUE",       0.75),
    ("version",     "VERSION",          0.75),
    ("url",         "FILE_REFERENCE",   0.75),
    ("link",        "FILE_REFERENCE",   0.50),
]

# Tokens that alone signal an ID column (only when the column is named
# something like "order_id", "product_id", "customer_id" — never "provider").
_ID_TOKENS: frozenset[str] = frozenset({"id", "uid", "uuid", "identifier", "ref"})


def _tokenize(col: str) -> list[str]:
    """Split a column name into lower-case tokens on _ and camelCase boundaries."""
    # Insert boundary before capital letters (camelCase)
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", col)
    return [t.lower() for t in re.split(r"[_\-\s]+", s) if t]


def _classify_column(table: str, col: str) -> ColumnType:
    """Classify one column using a three-tier heuristic.

    Tier 1 — Extra alias table (_EXTRA_ALIASES): explicit overrides, highest priority.
    Tier 2 — Exact alias lookup in the taxonomy YAML (confidence 0.90).
    Tier 3 — Whole-token rule scan (confidence from _TOKEN_RULES / _ID_TOKENS).
    Fallback — OTHER with confidence 0.0.

    _EXTRA_ALIASES takes priority over the YAML taxonomy so that manually
    curated corrections (e.g. order_item_id → ID, product_photos_qty → QUANTITY)
    are not overridden by generic taxonomy aliases.
    """
    col_lower = col.lower().strip()
    tokens = _tokenize(col)

    # ── Tier 1: explicit override table (highest priority) ───────────────
    if col_lower in _EXTRA_ALIASES:
        type_id, confidence = _EXTRA_ALIASES[col_lower]
    else:
        # ── Tier 2: taxonomy YAML exact alias ────────────────────────────
        type_id = _LOADER.type_id_from_alias(col_lower)
        if type_id:
            confidence = 0.90
        else:
            # ── Tier 3: whole-token scan ──────────────────────────────────
            type_id, confidence = _token_classify(tokens, col_lower)

    semantic_type = _TYPE_MAP.get(type_id, SemanticType.OTHER)
    pii_candidate = type_id in _PII_TAXONOMY_TYPES

    return ColumnType(
        table=table,
        column=col,
        semantic_type=semantic_type,
        confidence=confidence,
        pii_candidate=pii_candidate,
    )


def _token_classify(tokens: list[str], col_lower: str) -> tuple[str, float]:
    """Return (type_id, confidence) from whole-token rules.

    ID detection: the column must end with an ID-token OR have an ID-token
    as its LAST substantive token (avoids 'valid_flag', 'provider').
    """
    if not tokens:
        return "UNKNOWN", 0.0

    last_token = tokens[-1]

    # ID rule: last token is an id-indicator
    if last_token in _ID_TOKENS:
        return "SYSTEM_ID", 0.75

    # Exact single-word match for very short column names
    if len(tokens) == 1:
        for tok, tid, conf in _TOKEN_RULES:
            if tokens[0] == tok:
                return tid, conf
        return "UNKNOWN", 0.0

    # Multi-token: scan all tokens, pick first strong match
    best_tid: str | None = None
    best_conf: float = 0.0
    for token in tokens:
        for tok, tid, conf in _TOKEN_RULES:
            if token == tok and conf > best_conf:
                best_tid = tid
                best_conf = conf

    if best_tid:
        return best_tid, best_conf

    return "UNKNOWN", 0.0


def _read_headers(csv_path: Path) -> list[str]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        return next(reader, [])


def _read_table_samples(csv_path: Path, max_rows: int = 10) -> tuple[list[str], list[list[str]]]:
    """Read header and first max_rows sample rows from CSV."""
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        samples: list[list[str]] = []
        for _ in range(max_rows):
            try:
                row = next(reader)
                samples.append(row)
            except StopIteration:
                break
        return header, samples


def run(ctx: RunContext) -> AgentResult:
    """Step 1a & Step 2/3: hybrid classification with table context and rich report."""
    tables_dir: Path = ctx.inputs["tables"]

    if not tables_dir.exists():
        ctx.log("classify", "FAILED", evidence={"error": "tables/ folder not found"})
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.FAILED,
            message="Input tables/ folder not found.",
        )

    # Initialize Hybrid Classifier (combines Step 2 rules + Step 3 embeddings)
    hybrid_clf: HybridClassifier | None = None
    try:
        hybrid_clf = HybridClassifier()
    except Exception as exc:
        log_msg = f"HybridClassifier init failed ({exc}), falling back to direct rules"
        import logging
        logging.getLogger(__name__).warning(log_msg)

    all_columns: list[ColumnType] = []
    rich_columns: list[SemanticColumn] = []
    csv_files = list(tables_dir.glob("*.csv"))

    for csv_path in csv_files:
        table_name = csv_path.stem.lower().strip()
        try:
            headers, sample_rows = _read_table_samples(csv_path, max_rows=10)
        except Exception as exc:
            ctx.log("read_headers", "FAILED",
                    inputs=[str(csv_path)], evidence={"error": str(exc)})
            continue

        if hybrid_clf is not None:
            # Build TableSchema and ColumnSchema with sample values for context matching
            col_schemas = []
            for idx, col_name in enumerate(headers):
                vals = [r[idx] for r in sample_rows if idx < len(r)]
                col_schemas.append(ColumnSchema(
                    table=table_name,
                    column=col_name,
                    position=idx,
                    sample_values=vals,
                    nullable=True,
                ))
            table_schema = TableSchema(
                table=table_name,
                source_path=str(csv_path),
                source_format="csv",
                columns=col_schemas,
            )
            h_results = hybrid_clf.classify_table(table_schema)

            for h_res in h_results:
                sem_type = _TYPE_MAP.get(h_res.semantic_type, SemanticType.OTHER)
                is_pii = (
                    h_res.privacy_hint in ("LIKELY_PII", "POTENTIAL_PII")
                    or h_res.semantic_type in _PII_TAXONOMY_TYPES
                )
                all_columns.append(ColumnType(
                    table=h_res.table,
                    column=h_res.column,
                    semantic_type=sem_type,
                    confidence=round(h_res.confidence, 4),
                    pii_candidate=is_pii,
                ))

                c_status = (
                    ClassificationStatus.UNKNOWN if h_res.semantic_type == "UNKNOWN"
                    else (ClassificationStatus.NEEDS_REVIEW if h_res.review_required
                          else ClassificationStatus.AUTOMATIC)
                )
                p_hint = getattr(PrivacyHint, h_res.privacy_hint, PrivacyHint.NO_DIRECT_PII_INDICATOR)
                dec_evidence = []
                if isinstance(h_res.evidence, dict) and "decision" in h_res.evidence:
                    dec_evidence.append(str(h_res.evidence["decision"]))

                rich_columns.append(SemanticColumn(
                    source_table=h_res.table,
                    column_name=h_res.column,
                    technical_type="object",
                    semantic_group=h_res.semantic_group,
                    semantic_type=h_res.semantic_type,
                    privacy_hint=p_hint,
                    confidence_score=round(h_res.confidence, 4),
                    confidence_method=h_res.method,
                    evidence=dec_evidence,
                    review_required=h_res.review_required,
                    classification_status=c_status,
                    classifier_version=f"hybrid@{hybrid_clf._backend_name}@2.0",
                ))
        else:
            for col in headers:
                all_columns.append(_classify_column(table_name, col))

    pii_count     = sum(1 for c in all_columns if c.pii_candidate)
    low_conf      = sum(1 for c in all_columns if c.confidence < 0.5)
    unknown_count = sum(1 for c in all_columns if c.semantic_type == SemanticType.OTHER
                        and c.confidence == 0.0)

    model_label = f"hybrid@{hybrid_clf._backend_name}@2.0" if hybrid_clf else "rules@1.1"

    # 1. Pipeline standard report (contracts.intake.ColumnTypesReport)
    report = ColumnTypesReport(model=model_label, columns=all_columns)
    out_path = ctx.output("report")
    save(report, out_path)

    # 2. Rich proposal report (contracts.proposals.semantic_contracts.SemanticMetadata)
    outputs_dict: dict[str, Path] = {"report": out_path}
    if rich_columns:
        rich_report = SemanticMetadata(
            schema_version="1.0.0",
            taxonomy_version=_LOADER.version,
            run_id=ctx.run_id,
            dataset_name=tables_dir.name,
            columns=rich_columns,
            total_columns=len(rich_columns),
            classified_columns=sum(1 for c in rich_columns if c.semantic_type != "UNKNOWN"),
            unknown_columns=sum(1 for c in rich_columns if c.semantic_type == "UNKNOWN"),
            review_required_columns=sum(1 for c in rich_columns if c.review_required),
        )
        rich_path = ctx.output_dir / "semantic_metadata.json"
        save(rich_report, rich_path)
        outputs_dict["semantic_metadata"] = rich_path

    ctx.log(
        "classify", "SUCCESS",
        inputs=[str(tables_dir)],
        outputs=[str(out_path)],
        rule_version=f"column_types:{model_label}",
        evidence={
            "tables": len(csv_files),
            "columns": len(all_columns),
            "pii_candidates": pii_count,
            "low_confidence_columns": low_conf,
            "unknown_columns": unknown_count,
            "rich_report_generated": bool(rich_columns),
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs=outputs_dict,
        message=(f"Classified {len(all_columns)} columns across {len(csv_files)} table(s) via {model_label}. "
                 f"{pii_count} PII candidate(s), {low_conf} low-confidence (<0.5)."),
    )
