"""intake/semantic_detection/step2/pipeline.py — Step 2 Classification Pipeline.

Owner  : Samar / Malek  (Step 2)
Purpose: Top-level orchestration entrypoint for Step 2.
         Chains SchemaReader → NameNormalizer → RuleClassifier → AmbiguityHandler.
         Integrates with the BIFlow DAG via the same AgentResult / RunContext API
         used by Step 1 (intake/column_types.py).

Output contract: ``contracts.intake.ColumnTypesReport``
  (same as Step 1 but produced by the Step 2 rule engine, model="step2-rules@1.0")

Usage from DAG::

    from intake.semantic_detection.step2.pipeline import run
    result = run(ctx)

Standalone usage::

    from intake.semantic_detection.step2.pipeline import classify_directory
    report, ambiguity = classify_directory(Path("data/tables"))
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import SemanticType, save
from contracts.intake import ColumnType, ColumnTypesReport

from intake.semantic_detection.step2.schema_reader import read_schema_dir, TableSchema
from intake.semantic_detection.step2.name_normalizer import NameNormalizer
from intake.semantic_detection.step2.rule_classifier import RuleBasedClassifier, ClassificationResult
from intake.semantic_detection.step2.ambiguity_handler import AmbiguityHandler, AmbiguityReport


# ── Type mapping: taxonomy type_id → contracts.common.SemanticType ────────────
# Extends Step 1 mapping; new entries added for Step 2 taxonomy coverage.
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

_PII_TAXONOMY_TYPES: frozenset[str] = frozenset({
    "EMAIL", "PHONE", "PERSON_NAME", "PERSON_ID",
    "BIRTH_DATE", "AGE", "PERSONAL_ADDRESS", "NATIONAL_ID",
    "POSTAL_CODE", "COMMENT", "FREE_TEXT", "DESCRIPTION",
})


# ── Public helpers ─────────────────────────────────────────────────────────────

def classify_directory(
    tables_dir: Path,
    *,
    rules_yaml: Path | None = None,
    taxonomy_yaml: Path | None = None,
) -> tuple[ColumnTypesReport, AmbiguityReport]:
    """Classify all CSV/JSON schemas in *tables_dir* (Step 2 rule engine).

    Args:
        tables_dir: Directory containing CSV or JSON schema files.
        rules_yaml: Override path to classification_rules.yaml.
        taxonomy_yaml: Override path to semantic_types.yaml.

    Returns:
        Tuple of (ColumnTypesReport, AmbiguityReport).
    """
    # ── 1. Read schemas ───────────────────────────────────────────────────
    tables: list[TableSchema] = read_schema_dir(tables_dir)

    # ── 2. Classify ───────────────────────────────────────────────────────
    kwargs: dict[str, Any] = {}
    if rules_yaml:
        kwargs["rules_yaml"] = rules_yaml
    if taxonomy_yaml:
        kwargs["taxonomy_yaml"] = taxonomy_yaml
    classifier = RuleBasedClassifier(**kwargs)

    raw_results: list[ClassificationResult] = classifier.classify_tables(tables)

    # ── 3. Resolve ambiguity ──────────────────────────────────────────────
    handler = AmbiguityHandler()
    resolved_results, ambiguity_report = handler.process(raw_results)

    # ── 4. Build ColumnTypesReport (Step 1 contract) ──────────────────────
    column_types: list[ColumnType] = []
    for res in resolved_results:
        semantic_type = _TYPE_MAP.get(res.semantic_type, SemanticType.OTHER)
        pii = res.semantic_type in _PII_TAXONOMY_TYPES
        column_types.append(ColumnType(
            table=res.table,
            column=res.column,
            semantic_type=semantic_type,
            confidence=res.confidence,
            pii_candidate=pii,
        ))

    report = ColumnTypesReport(model="step2-rules@1.0", columns=column_types)
    return report, ambiguity_report


# ── DAG AgentResult entrypoint ─────────────────────────────────────────────────

def run(ctx: RunContext) -> AgentResult:
    """Step 2: rule-based column classification (DAG entrypoint).

    Reads CSV/JSON tables from ctx.inputs["tables"].
    Writes ColumnTypesReport to ctx.output("report").
    Also writes AmbiguityReport to ctx.output("ambiguity_report").
    """
    tables_dir: Path = ctx.inputs["tables"]

    if not tables_dir.exists():
        ctx.log("classify_step2", "FAILED", evidence={"error": "tables/ folder not found"})
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.FAILED,
            message="Input tables/ folder not found.",
        )

    report, ambiguity = classify_directory(tables_dir)

    pii_count     = sum(1 for c in report.columns if c.pii_candidate)
    low_conf      = sum(1 for c in report.columns if c.confidence < 0.5)
    unknown_count = sum(1 for c in report.columns
                        if c.semantic_type == SemanticType.OTHER and c.confidence == 0.0)

    out_path     = ctx.output("report")
    amb_path     = ctx.output("ambiguity_report")
    save(report, out_path)

    amb_path.parent.mkdir(parents=True, exist_ok=True)
    amb_path.write_text(
        json.dumps(ambiguity.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    ctx.log(
        "classify_step2", "SUCCESS",
        inputs=[str(tables_dir)],
        outputs=[str(out_path), str(amb_path)],
        rule_version="step2-rules@1.0",
        evidence={
            "tables": len({c.table for c in report.columns}),
            "columns": len(report.columns),
            "pii_candidates": pii_count,
            "low_confidence_columns": low_conf,
            "unknown_columns": unknown_count,
            "pending_review": len(ambiguity.review_flags),
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"report": out_path, "ambiguity_report": amb_path},
        message=(
            f"Step 2 classified {len(report.columns)} columns. "
            f"{pii_count} PII candidates, {unknown_count} unknown, "
            f"{len(ambiguity.review_flags)} pending review."
        ),
    )
