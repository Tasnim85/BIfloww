"""tests/test_step2_fixes.py — Validation of the 3 targeted Step 2 rule fixes.

Owner  : Malek  (BIFlow Semantic Detection — Step 2 fix validation)
Branch : fix/malek-step2-step3-similarity

These tests verify that the three priority-0 override rules injected into
``intake/semantic_detection/config/classification_rules.yaml`` correct the
divergences identified in STEP2_INTEGRATION_PROPOSAL.md:

  Fix 1  — review_id    : was TEXT(PII=True)      → must be SYSTEM_ID(PII=False)
  Fix 2  — customer_unique_id : was SYSTEM_ID(PII=False) → must be PERSON_ID(LIKELY_PII)
  Fix 3  — payment_installments: was NUMBER(PII=True) → must be QUANTITY(PII=False)

Run with:
    cd BIfloww_integration
    python -m pytest tests/test_step2_fixes.py -v
"""
from __future__ import annotations

import pytest

from intake.semantic_detection.step2.rule_classifier import RuleBasedClassifier
from intake.semantic_detection.step2.schema_reader import ColumnSchema, TableSchema


# ── Fixture: classifier (one shared instance for performance) ─────────────────

@pytest.fixture(scope="module")
def clf() -> RuleBasedClassifier:
    return RuleBasedClassifier()


def _make_col(column: str, table: str = "test_table", samples=None) -> ColumnSchema:
    """Helper: create a minimal ColumnSchema."""
    return ColumnSchema(
        table=table,
        column=column,
        position=0,
        declared_type=None,
        sample_values=samples or [],
        nullable=True,
    )


def _make_table(columns: list[str], table: str = "test_table") -> TableSchema:
    return TableSchema(
        table=table,
        columns=[ColumnSchema(table=table, column=c, position=i, sample_values=[], nullable=True)
                 for i, c in enumerate(columns)],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 1 — review_id must be SYSTEM_ID (not TEXT), PII = False
# ═══════════════════════════════════════════════════════════════════════════════

class TestFix1ReviewId:
    """review_id: Step 2 used to return TEXT (tier=context, PII=True).
    After Fix 1 (ID_SUFFIX_OVERRIDE_RULE, priority=0), it must be SYSTEM_ID."""

    def test_review_id_type_is_system_id(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("review_id", "order_reviews")
        result = clf.classify_column(col)
        assert result.semantic_type == "SYSTEM_ID", (
            f"review_id → expected SYSTEM_ID, got {result.semantic_type} "
            f"(tier={result.match_tier}, rule={result.matched_rule})"
        )

    def test_review_id_pii_is_false(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("review_id", "order_reviews")
        result = clf.classify_column(col)
        # SYSTEM_ID privacy_hint must be NO_DIRECT_PII_INDICATOR (not LIKELY_PII)
        assert result.privacy_hint in ("NO_DIRECT_PII_INDICATOR", "POTENTIAL_PII"), (
            f"review_id → expected non-PII hint, got {result.privacy_hint}"
        )

    def test_review_id_confidence_high(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("review_id", "order_reviews")
        result = clf.classify_column(col)
        assert result.confidence >= 0.85, (
            f"review_id fix rule confidence too low: {result.confidence}"
        )

    def test_order_item_id_taxonomy_alias(self, clf: RuleBasedClassifier) -> None:
        """order_item_id is explicitly listed as a QUANTITY alias in semantic_types.yaml
        (Olist: it is a sequential counter 1..N per order, not a surrogate key).
        The taxonomy alias tier takes precedence over the _id-suffix keyword rule.
        This confirms the alias tier cannot be overridden by a keyword-tier rule.
        """
        col = _make_col("order_item_id", "order_items")
        result = clf.classify_column(col)
        # Taxonomy alias wins: QUANTITY (sequential item counter in Olist)
        assert result.semantic_type == "QUANTITY", (
            f"order_item_id → expected QUANTITY (taxonomy alias), got {result.semantic_type} "
            f"(tier={result.match_tier})"
        )
        assert result.match_tier == "alias", (
            f"order_item_id → expected alias tier, got {result.match_tier}"
        )

    def test_session_id_also_fixed(self, clf: RuleBasedClassifier) -> None:
        """Any *_id column should resolve to SYSTEM_ID via the override rule."""
        col = _make_col("session_id", "web_events")
        result = clf.classify_column(col)
        assert result.semantic_type == "SYSTEM_ID", (
            f"session_id → expected SYSTEM_ID, got {result.semantic_type}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 2 — customer_unique_id must be PERSON_ID (PII = LIKELY_PII)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFix2CustomerUniqueId:
    """customer_unique_id: was SYSTEM_ID(PII=False) → must be PERSON_ID(LIKELY_PII)."""

    def test_customer_unique_id_type_is_person_id(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("customer_unique_id", "customers")
        result = clf.classify_column(col)
        assert result.semantic_type == "PERSON_ID", (
            f"customer_unique_id → expected PERSON_ID, got {result.semantic_type} "
            f"(tier={result.match_tier}, rule={result.matched_rule})"
        )

    def test_customer_unique_id_pii_is_true(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("customer_unique_id", "customers")
        result = clf.classify_column(col)
        assert result.privacy_hint in ("POTENTIAL_PII", "LIKELY_PII"), (
            f"customer_unique_id → expected PII hint (POTENTIAL_PII), got {result.privacy_hint}"
        )

    def test_customer_id_also_person_id(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("customer_id", "customers")
        result = clf.classify_column(col)
        assert result.semantic_type == "PERSON_ID", (
            f"customer_id → expected PERSON_ID, got {result.semantic_type}"
        )

    def test_client_id_also_person_id(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("client_id", "clients")
        result = clf.classify_column(col)
        assert result.semantic_type == "PERSON_ID", (
            f"client_id → expected PERSON_ID, got {result.semantic_type}"
        )

    def test_seller_id_is_not_person_id(self, clf: RuleBasedClassifier) -> None:
        """seller_id must NOT be reclassified as PERSON_ID — it is SELLER_ID."""
        col = _make_col("seller_id", "sellers")
        result = clf.classify_column(col)
        assert result.semantic_type != "PERSON_ID", (
            f"seller_id should not be PERSON_ID, got {result.semantic_type}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# FIX 3 — payment_installments must be QUANTITY (PII = False)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFix3PaymentInstallments:
    """payment_installments: was NUMBER(PII=True) → must be QUANTITY(PII=False)."""

    def test_payment_installments_type_is_quantity(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("payment_installments", "order_payments")
        result = clf.classify_column(col)
        assert result.semantic_type == "QUANTITY", (
            f"payment_installments → expected QUANTITY, got {result.semantic_type} "
            f"(tier={result.match_tier}, rule={result.matched_rule})"
        )

    def test_payment_installments_pii_is_false(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("payment_installments", "order_payments")
        result = clf.classify_column(col)
        assert result.privacy_hint == "NO_DIRECT_PII_INDICATOR", (
            f"payment_installments → expected NO_DIRECT_PII_INDICATOR, got {result.privacy_hint}"
        )

    def test_payment_installments_not_pii_group(self, clf: RuleBasedClassifier) -> None:
        col = _make_col("payment_installments", "order_payments")
        result = clf.classify_column(col)
        assert result.semantic_group == "QUANTITATIVE_DATA", (
            f"payment_installments → expected QUANTITATIVE_DATA group, got {result.semantic_group}"
        )

    def test_num_installments_variant(self, clf: RuleBasedClassifier) -> None:
        """num_installments is a synonym — must also resolve to QUANTITY."""
        col = _make_col("num_installments", "payments")
        result = clf.classify_column(col)
        assert result.semantic_type == "QUANTITY", (
            f"num_installments → expected QUANTITY, got {result.semantic_type}"
        )

    def test_payment_value_is_not_quantity(self, clf: RuleBasedClassifier) -> None:
        """payment_value must remain PAYMENT_AMOUNT — not confused with QUANTITY."""
        col = _make_col("payment_value", "order_payments")
        result = clf.classify_column(col)
        assert result.semantic_type != "QUANTITY", (
            f"payment_value should NOT be QUANTITY — it should be PAYMENT_AMOUNT or similar"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Regression tests — pre-existing correct classifications must not regress
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegressionStability:
    """Ensure the 3 fix rules do not break previously correct classifications."""

    @pytest.mark.parametrize("column,table,expected_type", [
        ("order_id",            "orders",         "ORDER_ID"),
        ("product_id",          "order_items",    "PRODUCT_ID"),
        ("seller_id",           "sellers",        "SELLER_ID"),
        ("order_purchase_timestamp", "orders",    "DATETIME"),
        ("order_status",        "orders",         "STATUS"),
        ("payment_value",       "order_payments", "PAYMENT_AMOUNT"),
        ("customer_city",       "customers",      "CITY"),
        ("customer_state",      "customers",      "STATE"),
        ("product_category_name", "products",     "PRODUCT_CATEGORY"),
        ("review_score",        "order_reviews",  "RATING"),
        ("freight_value",       "order_items",    "FREIGHT_COST"),
    ])
    def test_pre_existing_classifications_stable(
        self,
        clf: RuleBasedClassifier,
        column: str,
        table: str,
        expected_type: str,
    ) -> None:
        col = _make_col(column, table)
        result = clf.classify_column(col)
        assert result.semantic_type == expected_type, (
            f"REGRESSION: {table}.{column} → expected {expected_type}, "
            f"got {result.semantic_type} (tier={result.match_tier})"
        )
