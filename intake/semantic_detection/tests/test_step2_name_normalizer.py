"""Tests for Step 2 — Name Normalizer.

Owner: Samar / Malek (Step 2)
"""
from __future__ import annotations

import pytest

from intake.semantic_detection.step2.name_normalizer import NameNormalizer, NormResult, _split_camel


# ── Unit tests for _split_camel ────────────────────────────────────────────────

class TestSplitCamel:
    def test_simple_camel(self) -> None:
        assert _split_camel("productQty") == "product_qty"

    def test_pascal_case(self) -> None:
        assert _split_camel("ProductQty") == "product_qty"

    def test_consecutive_uppers(self) -> None:
        # XMLParser → xml_parser
        result = _split_camel("XMLParser")
        assert "xml" in result and "parser" in result

    def test_already_snake(self) -> None:
        assert _split_camel("order_id") == "order_id"

    def test_no_change_for_lowercase(self) -> None:
        assert _split_camel("price") == "price"


# ── Normalizer tests ───────────────────────────────────────────────────────────

class TestNameNormalizer:

    @pytest.fixture()
    def norm(self) -> NameNormalizer:
        return NameNormalizer()

    # Basic normalisation
    def test_returns_norm_result(self, norm: NameNormalizer) -> None:
        result = norm.normalize("price")
        assert isinstance(result, NormResult)

    def test_original_preserved(self, norm: NameNormalizer) -> None:
        result = norm.normalize("OrderID")
        assert result.original == "OrderID"

    def test_normalized_key_lowercase(self, norm: NameNormalizer) -> None:
        result = norm.normalize("CustomerName")
        assert result.normalized_key == result.normalized_key.lower()

    # Abbreviation expansion
    def test_qty_expanded(self, norm: NameNormalizer) -> None:
        result = norm.normalize("product_qty")
        assert "quantity" in result.tokens
        assert "qty" in result.expanded_abbreviations

    def test_amt_expanded(self, norm: NameNormalizer) -> None:
        result = norm.normalize("order_amt")
        assert "amount" in result.tokens

    def test_dt_expanded(self, norm: NameNormalizer) -> None:
        result = norm.normalize("order_dt")
        assert "date" in result.tokens

    # Business terms preserved
    def test_sku_preserved(self, norm: NameNormalizer) -> None:
        result = norm.normalize("product_sku")
        assert "sku" in result.tokens
        assert "sku" in result.preserved_business_terms

    def test_kpi_preserved(self, norm: NameNormalizer) -> None:
        result = norm.normalize("monthly_kpi")
        assert "kpi" in result.tokens

    def test_vat_preserved(self, norm: NameNormalizer) -> None:
        result = norm.normalize("vat_amount")
        assert "vat" in result.tokens

    # CamelCase splitting
    def test_camel_case_split(self, norm: NameNormalizer) -> None:
        result = norm.normalize("ProductQty")
        assert "product" in result.tokens

    # Numeric removal
    def test_numeric_tokens_removed(self, norm: NameNormalizer) -> None:
        result = norm.normalize("col_1_price")
        assert "1" not in result.tokens

    # Multi-word columns
    def test_compound_column(self, norm: NameNormalizer) -> None:
        result = norm.normalize("review_comment_message")
        assert "review" in result.tokens
        assert "comment" in result.tokens
        assert "message" in result.tokens

    # Empty/edge cases
    def test_empty_string(self, norm: NameNormalizer) -> None:
        result = norm.normalize("")
        assert isinstance(result, NormResult)

    def test_underscore_only(self, norm: NameNormalizer) -> None:
        result = norm.normalize("___")
        assert isinstance(result, NormResult)

    # Custom abbreviations
    def test_custom_abbreviation(self) -> None:
        norm = NameNormalizer(abbreviations={"rev": "revenue"})
        result = norm.normalize("monthly_rev")
        assert "revenue" in result.tokens

    # normalize_many
    def test_normalize_many(self, norm: NameNormalizer) -> None:
        results = norm.normalize_many(["price", "qty", "email"])
        assert len(results) == 3
        assert all(isinstance(r, NormResult) for r in results)

    # Specific BIFlow columns
    @pytest.mark.parametrize("col,expected_token", [
        ("order_id", "id"),
        ("customer_zip_code_prefix", "postal"),
        ("review_score", "score"),
        ("product_weight_g", "weight"),
        ("geolocation_lat", "latitude"),
        ("geolocation_lng", "longitude"),
    ])
    def test_biflow_columns(self, norm: NameNormalizer, col: str, expected_token: str) -> None:
        result = norm.normalize(col)
        assert expected_token in result.tokens, (
            f"Expected {expected_token!r} in tokens for {col!r}, got {result.tokens}"
        )
