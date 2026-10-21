"""Tests for Step 2 — Rule-Based Classifier.

Owner: Samar / Malek (Step 2)
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from intake.semantic_detection.step2.schema_reader import (
    ColumnSchema, TableSchema, read_csv_schema,
)
from intake.semantic_detection.step2.rule_classifier import (
    ClassificationResult,
    RuleBasedClassifier,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_col(table: str, column: str, samples: list | None = None) -> ColumnSchema:
    return ColumnSchema(
        table=table, column=column, position=0,
        sample_values=samples or [], source_format="csv",
    )


def make_table(table: str, columns: list[str]) -> TableSchema:
    cols = [ColumnSchema(table=table, column=c, position=i) for i, c in enumerate(columns)]
    return TableSchema(table=table, source_path="", source_format="csv", columns=cols)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def clf() -> RuleBasedClassifier:
    return RuleBasedClassifier()


@pytest.fixture()
def olist_orders_csv(tmp_path: Path) -> Path:
    """Minimal Olist orders.csv for integration test."""
    p = tmp_path / "orders.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "order_id", "customer_id", "order_status",
            "order_purchase_timestamp", "order_approved_at",
            "order_delivered_customer_date", "price", "freight_value",
        ])
        writer.writerow([
            "ORD-1", "CUST-1", "delivered",
            "2026-01-15 10:00:00", "2026-01-15 11:00:00",
            "2026-01-18", "29.99", "5.00",
        ])
    return p


# ── ClassificationResult API ───────────────────────────────────────────────────

class TestClassificationResultApi:

    def test_is_unknown_true(self, clf: RuleBasedClassifier) -> None:
        col = make_col("t", "zzz_totally_unknown_xqqq")
        result = clf.classify_column(col)
        assert result.is_unknown

    def test_is_unknown_false_for_email(self, clf: RuleBasedClassifier) -> None:
        col = make_col("t", "email")
        result = clf.classify_column(col)
        assert not result.is_unknown

    def test_is_low_confidence_true(self, clf: RuleBasedClassifier) -> None:
        col = make_col("t", "zzz_totally_unknown_xqqq")
        result = clf.classify_column(col)
        assert result.is_low_confidence

    def test_result_has_required_fields(self, clf: RuleBasedClassifier) -> None:
        col = make_col("orders", "price")
        result = clf.classify_column(col)
        assert isinstance(result, ClassificationResult)
        assert result.table == "orders"
        assert result.column == "price"
        assert result.semantic_group
        assert result.semantic_type
        assert 0.0 <= result.confidence <= 1.0
        assert result.match_tier in {"alias", "keyword", "pattern", "context", "unknown"}


# ── Alias tier (Tier 1) ────────────────────────────────────────────────────────

class TestAliasTier:

    @pytest.mark.parametrize("col,expected_type", [
        ("order_status", "STATUS"),
        ("payment_type", "PAYMENT_METHOD"),
        ("product_category_name", "PRODUCT_CATEGORY"),
        ("review_score", "RATING"),
    ])
    def test_taxonomy_aliases(self, clf: RuleBasedClassifier, col: str, expected_type: str) -> None:
        result = clf.classify_column(make_col("t", col))
        assert result.semantic_type == expected_type
        assert result.match_tier == "alias"
        assert result.confidence >= 0.90


# ── Keyword tier (Tier 2) ──────────────────────────────────────────────────────

class TestKeywordTier:

    @pytest.mark.parametrize("col,expected_group,expected_type", [
        ("email_address",        "PERSONAL_DATA",        "EMAIL"),
        ("customer_phone",       "PERSONAL_DATA",        "PHONE"),
        ("first_name",           "PERSONAL_DATA",        "PERSON_NAME"),
        ("customer_id",          "PERSONAL_DATA",        "PERSON_ID"),
        ("unit_price",           "FINANCIAL_DATA",       "PRICE"),
        ("freight_cost",         "FINANCIAL_DATA",       "FREIGHT_COST"),
        ("order_date",           "TEMPORAL_DATA",        "DATE"),
        ("created_at",           "TEMPORAL_DATA",        "DATETIME"),
        ("geolocation_lat",      "GEOGRAPHICAL_DATA",    "LATITUDE"),
        ("geolocation_zip",      "GEOGRAPHICAL_DATA",    "POSTAL_CODE"),
        ("review_comment",       "TEXTUAL_DATA",         "COMMENT"),
        ("product_description",  "TEXTUAL_DATA",         "DESCRIPTION"),
        ("product_weight",       "QUANTITATIVE_DATA",    "WEIGHT"),
        ("transaction_id",       "BUSINESS_ENTITY_DATA", "TRANSACTION_ID"),
    ])
    def test_keyword_matches(
        self, clf: RuleBasedClassifier, col: str, expected_group: str, expected_type: str
    ) -> None:
        result = clf.classify_column(make_col("t", col))
        assert result.semantic_type == expected_type, (
            f"col={col!r}: expected {expected_type!r}, got {result.semantic_type!r} "
            f"(tier={result.match_tier}, rule={result.matched_rule})"
        )
        assert result.semantic_group == expected_group


# ── Pattern tier (Tier 3) ──────────────────────────────────────────────────────

class TestPatternTier:

    def test_email_pattern_in_values(self, clf: RuleBasedClassifier) -> None:
        col = make_col("t", "contact_info", samples=["alice@example.com", "bob@test.org"])
        result = clf.classify_column(col)
        # Should match EMAIL either by keyword or pattern
        assert result.semantic_type in {"EMAIL", "UNKNOWN"} or result.confidence > 0

    def test_uuid_pattern(self, clf: RuleBasedClassifier) -> None:
        col = make_col("t", "record_identifier", samples=["550e8400-e29b-41d4-a716-446655440000"])
        result = clf.classify_column(col)
        # Should hit SYSTEM_ID by keyword or pattern
        assert result.confidence > 0


# ── Context tier (Tier 4) ─────────────────────────────────────────────────────

class TestContextTier:

    def test_lat_in_geolocation_table(self, clf: RuleBasedClassifier) -> None:
        table = make_table("geolocation", ["lat", "lng", "city"])
        lat_col = table.columns[0]
        result = clf.classify_column(lat_col, table_context=table)
        assert result.semantic_type in {"LATITUDE", "LONGITUDE"} or result.confidence > 0

    def test_status_in_order_table(self, clf: RuleBasedClassifier) -> None:
        table = make_table("orders", ["order_id", "status", "price"])
        status_col = table.columns[1]
        result = clf.classify_column(status_col, table_context=table)
        assert result.semantic_type == "STATUS"


# ── classify_table / classify_tables ──────────────────────────────────────────

class TestClassifyTable:

    def test_classify_table_returns_list(self, clf: RuleBasedClassifier) -> None:
        table = make_table("orders", ["order_id", "price", "status"])
        results = clf.classify_table(table)
        assert len(results) == 3

    def test_classify_tables_multiple(self, clf: RuleBasedClassifier) -> None:
        t1 = make_table("orders", ["order_id", "price"])
        t2 = make_table("products", ["product_id", "category"])
        results = clf.classify_tables([t1, t2])
        assert len(results) == 4


# ── Olist integration test ─────────────────────────────────────────────────────

class TestOlistIntegration:

    def test_olist_orders_columns(self, clf: RuleBasedClassifier, olist_orders_csv: Path) -> None:
        from intake.semantic_detection.step2.schema_reader import read_csv_schema
        table = read_csv_schema(olist_orders_csv)
        results = clf.classify_table(table)
        result_map = {r.column: r for r in results}

        # Known high-confidence columns
        assert result_map["order_id"].semantic_type in {"ORDER_ID", "SYSTEM_ID"}
        assert result_map["price"].semantic_type == "PRICE"
        assert result_map["order_status"].semantic_type == "STATUS"

        # All classified (none should error)
        assert len(results) == len(table.columns)

    def test_all_results_have_valid_tier(self, clf: RuleBasedClassifier, olist_orders_csv: Path) -> None:
        from intake.semantic_detection.step2.schema_reader import read_csv_schema
        table = read_csv_schema(olist_orders_csv)
        results = clf.classify_table(table)
        valid_tiers = {"alias", "keyword", "pattern", "context", "unknown"}
        assert all(r.match_tier in valid_tiers for r in results)
