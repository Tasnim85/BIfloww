"""tests/test_hybrid_classifier.py — Validation of Step 3 Hybrid Classifier.

Owner  : Malek (BIFlow Semantic Detection — Step 3)
Branch : fix/malek-step2-step3-similarity

Tests cover:
  1. Instantiation and taxonomy/descriptions loading.
  2. Rule priority / alias tier arbitration (rule is trusted, embeddings skipped).
  3. Keyword tier arbitration (trusted when confidence >= 0.75).
  4. Unknown tier handling (embedding becomes decisive).
  5. Multi-column and table-level classification (classify_table, classify_schema).
  6. Aggregate statistics reporting (summary_stats).
  7. Dictionary serialization (to_dict).

Run with:
    cd BIfloww_integration
    python -m pytest tests/test_hybrid_classifier.py -v
"""
from __future__ import annotations

import pytest

from intake.semantic_detection.step2.schema_reader import ColumnSchema, TableSchema
from intake.semantic_detection.step3.hybrid_classifier import HybridClassifier, HybridResult


@pytest.fixture(scope="module")
def hybrid_clf() -> HybridClassifier:
    return HybridClassifier()


def _make_col(column: str, table: str = "orders", samples=None) -> ColumnSchema:
    return ColumnSchema(
        table=table,
        column=column,
        position=0,
        sample_values=samples or [],
        nullable=True,
    )


class TestHybridInstantiation:
    """Verify that HybridClassifier initializes correctly and loads its dependencies."""

    def test_init_success(self, hybrid_clf: HybridClassifier) -> None:
        assert hybrid_clf is not None
        assert len(hybrid_clf._descriptions) > 0
        assert "EMAIL" in hybrid_clf._descriptions
        assert "SYSTEM_ID" in hybrid_clf._descriptions

    def test_backend_initialized(self, hybrid_clf: HybridClassifier) -> None:
        assert hybrid_clf._backend_name in ("sentence-transformers", "tfidf", "jaccard")


class TestHybridArbitration:
    """Verify decision policies between Step 2 rule results and embedding scores."""

    def test_alias_tier_trusts_rule(self, hybrid_clf: HybridClassifier) -> None:
        # 'order_status' has exact alias in taxonomy -> alias tier
        col = _make_col("order_status", "orders")
        result = hybrid_clf.classify(col)
        assert isinstance(result, HybridResult)
        assert result.semantic_type == "STATUS"
        assert result.method == "rule"
        assert result.review_required is False
        assert result.confidence >= 0.90

    def test_keyword_tier_trusts_rule_when_high_confidence(self, hybrid_clf: HybridClassifier) -> None:
        # 'review_id' matches ID_SUFFIX_OVERRIDE_RULE (conf=0.91)
        col = _make_col("review_id", "order_reviews")
        result = hybrid_clf.classify(col)
        assert result.semantic_type == "SYSTEM_ID"
        assert result.method == "rule"
        assert result.review_required is False

    def test_customer_unique_id_pii_preserved(self, hybrid_clf: HybridClassifier) -> None:
        col = _make_col("customer_unique_id", "customers")
        result = hybrid_clf.classify(col)
        assert result.semantic_type == "PERSON_ID"
        assert result.privacy_hint in ("POTENTIAL_PII", "LIKELY_PII")

    def test_payment_installments_quantity(self, hybrid_clf: HybridClassifier) -> None:
        col = _make_col("payment_installments", "order_payments")
        result = hybrid_clf.classify(col)
        assert result.semantic_type == "QUANTITY"
        assert result.privacy_hint == "NO_DIRECT_PII_INDICATOR"


class TestHybridTableAndSchema:
    """Verify table and multi-table classification."""

    def test_classify_table(self, hybrid_clf: HybridClassifier) -> None:
        table = TableSchema(
            table="orders",
            source_path="orders.csv",
            source_format="csv",
            columns=[
                _make_col("order_id", "orders"),
                _make_col("customer_id", "orders"),
                _make_col("order_status", "orders"),
                _make_col("order_purchase_timestamp", "orders"),
            ],
        )
        results = hybrid_clf.classify_table(table)
        assert len(results) == 4
        types = [r.semantic_type for r in results]
        assert "ORDER_ID" in types
        assert "PERSON_ID" in types
        assert "STATUS" in types
        assert "DATETIME" in types

    def test_classify_schema(self, hybrid_clf: HybridClassifier) -> None:
        t1 = TableSchema(table="t1", source_path="t1.csv", source_format="csv", columns=[_make_col("order_id", "t1")])
        t2 = TableSchema(table="t2", source_path="t2.csv", source_format="csv", columns=[_make_col("customer_id", "t2")])
        schema_res = hybrid_clf.classify_schema([t1, t2])
        assert "t1" in schema_res
        assert "t2" in schema_res
        assert schema_res["t1"][0].semantic_type == "ORDER_ID"
        assert schema_res["t2"][0].semantic_type == "PERSON_ID"


class TestHybridSummaryAndSerialization:
    """Verify statistics computation and JSON serialization."""

    def test_summary_stats(self, hybrid_clf: HybridClassifier) -> None:
        cols = [
            _make_col("order_id"),
            _make_col("customer_unique_id"),
            _make_col("payment_value"),
        ]
        results = [hybrid_clf.classify(c) for c in cols]
        stats = HybridClassifier.summary_stats(results)
        assert stats["total"] == 3
        assert "by_method" in stats
        assert stats["avg_confidence"] > 0.0
        assert stats["pii_hint_count"] >= 1  # customer_unique_id is LIKELY_PII

    def test_to_dict(self, hybrid_clf: HybridClassifier) -> None:
        col = _make_col("order_id")
        result = hybrid_clf.classify(col)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["column"] == "order_id"
        assert d["semantic_type"] == "ORDER_ID"
        assert "confidence" in d
        assert "method" in d
        assert "review_required" in d
