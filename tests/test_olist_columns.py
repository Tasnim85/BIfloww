"""tests/test_olist_columns.py — Golden tests for intake/column_types.py.

Verifies the complete Olist column classification table specified in the
audit correction mission, including counter-examples.
Also contains an end-to-end test with context_for() and a real CSV.
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.common import SemanticType
from intake.column_types import _classify_column, _tokenize


# ── Helper ────────────────────────────────────────────────────────────────
def classify(col: str) -> tuple[SemanticType, bool, float]:
    ct = _classify_column("test_table", col)
    return ct.semantic_type, ct.pii_candidate, ct.confidence


# ── Golden table ──────────────────────────────────────────────────────────
GOLDEN: list[tuple[str, SemanticType, bool]] = [
    # column_name                        expected_type            pii
    ("customer_id",                      SemanticType.ID,         True),
    ("customer_unique_id",               SemanticType.ID,         True),
    ("customer_zip_code_prefix",         SemanticType.ZIP_CODE,   True),
    ("customer_city",                    SemanticType.CITY,       False),
    ("customer_state",                   SemanticType.STATE,      False),
    ("order_id",                         SemanticType.ID,         False),
    ("order_status",                     SemanticType.CATEGORY,   False),
    ("order_purchase_timestamp",         SemanticType.DATETIME,   False),
    ("order_delivered_customer_date",    SemanticType.DATE,       False),
    ("order_item_id",                    SemanticType.ID,         False),
    ("shipping_limit_date",              SemanticType.DATE,       False),
    ("price",                            SemanticType.AMOUNT,     False),
    ("freight_value",                    SemanticType.AMOUNT,     False),
    ("payment_sequential",               SemanticType.NUMBER,     False),
    ("payment_installments",             SemanticType.QUANTITY,   False),
    ("payment_value",                    SemanticType.AMOUNT,     False),
    ("payment_type",                     SemanticType.CATEGORY,   False),
    ("review_id",                        SemanticType.ID,         False),
    ("review_score",                     SemanticType.NUMBER,     False),
    ("review_comment_title",             SemanticType.TEXT,       True),
    ("review_comment_message",           SemanticType.TEXT,       True),
    ("product_id",                       SemanticType.ID,         False),
    ("product_category_name",            SemanticType.CATEGORY,   False),
    ("product_weight_g",                 SemanticType.NUMBER,     False),
    ("product_photos_qty",               SemanticType.QUANTITY,   False),
    ("geolocation_lat",                  SemanticType.NUMBER,     False),
    ("geolocation_lng",                  SemanticType.NUMBER,     False),
    ("seller_id",                        SemanticType.ID,         False),
]

@pytest.mark.parametrize("col, expected_type, expected_pii", GOLDEN)
def test_golden_olist(col: str, expected_type: SemanticType, expected_pii: bool):
    sem_type, pii, conf = classify(col)
    assert sem_type == expected_type, (
        f"Column '{col}': got {sem_type}, expected {expected_type}"
    )
    assert pii == expected_pii, (
        f"Column '{col}': pii_candidate={pii}, expected {expected_pii}"
    )
    assert 0.0 <= conf <= 1.0, f"Column '{col}': confidence {conf} out of [0,1]"


# ── Counter-examples: these must NOT be classified as ID ──────────────────
@pytest.mark.parametrize("col", ["valid_flag", "provider", "is_valid", "provider_name"])
def test_not_id(col: str):
    sem_type, _, _ = classify(col)
    assert sem_type != SemanticType.ID, (
        f"Column '{col}' was incorrectly classified as ID"
    )


# ── Tokenizer unit tests ──────────────────────────────────────────────────
def test_tokenize_snake():
    assert _tokenize("customer_unique_id") == ["customer", "unique", "id"]

def test_tokenize_camel():
    assert _tokenize("orderId") == ["order", "id"]

def test_tokenize_simple():
    assert _tokenize("price") == ["price"]

def test_tokenize_mixed():
    assert _tokenize("valid_flag") == ["valid", "flag"]


# ── Confidence tests ──────────────────────────────────────────────────────
def test_exact_alias_high_confidence():
    _, _, conf = classify("customer_email")
    assert conf >= 0.85, f"Exact alias should have conf>=0.85, got {conf}"

def test_unknown_zero_confidence():
    sem, _, conf = classify("xyz_qrst_zzzz")
    assert sem == SemanticType.OTHER
    assert conf == 0.0


# ── End-to-end test with context_for + CSV + registry ────────────────────
def test_e2e_with_context_for(tmp_path):
    """Full pipeline step: write CSV, run step, read output with registry."""
    from contracts.pipeline import context_for
    from contracts.registry import read_output

    # Write a tiny CSV
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    csv_path = tables_dir / "orders.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "customer_id", "order_status",
                    "payment_value", "valid_flag"])
        w.writerow(["ord1", "cust1", "delivered", "100.0", "true"])

    # Build ctx manually (no journal/db side effects in tmp_path)
    from contracts.agent import RunContext
    import uuid
    run_id = f"test_{uuid.uuid4().hex[:6]}"
    output_dir = tmp_path / run_id / "column_types"
    output_dir.mkdir(parents=True)

    ctx = RunContext(
        run_id=run_id,
        agent="column_types",
        inputs={"tables": tables_dir},
        output_dir=output_dir,
        journal=tmp_path / "journal.db",
    )

    from intake.column_types import run
    result = run(ctx)

    assert result.status.value == "success", f"Step failed: {result.message}"

    report_path = output_dir / "column_types.json"
    assert report_path.exists(), "column_types.json not written"

    report = read_output(report_path, "column_types.report")
    by_col = {c.column: c for c in report.columns}

    assert by_col["order_id"].semantic_type   == SemanticType.ID
    assert by_col["customer_id"].pii_candidate is True
    assert by_col["order_status"].semantic_type == SemanticType.CATEGORY
    assert by_col["payment_value"].semantic_type == SemanticType.AMOUNT
    # valid_flag must NOT be ID
    assert by_col["valid_flag"].semantic_type != SemanticType.ID
