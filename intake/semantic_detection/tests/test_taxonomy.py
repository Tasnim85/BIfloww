"""test_taxonomy.py — 20+ tests for the semantic taxonomy and validators.

Tests cover:
  T01-T06: YAML structure, groups, types, uniqueness, descriptions, version
  T07-T12: Loader API, pair validation, aliases, privacy hints
  T13-T20: Edge cases, extensibility, UNKNOWN_DATA, required groups
"""
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "config" / "semantic_types.yaml"

from intake.semantic_detection.src.taxonomy_loader import TaxonomyLoader
from intake.semantic_detection.src.taxonomy_validator import (
    ValidationResult,
    validate_group_type_pair,
    validate_taxonomy_file,
)


@pytest.fixture
def loader():
    return TaxonomyLoader(TAXONOMY_PATH)


@pytest.fixture
def raw_data():
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── T01: YAML is valid ──────────────────────────────────────────────────
class TestYAMLStructure:
    def test_t01_yaml_is_valid(self):
        result = validate_taxonomy_file(TAXONOMY_PATH)
        assert result.valid, f"Taxonomy invalid: {result.errors}"

    def test_t02_all_required_groups_exist(self):
        result = validate_taxonomy_file(TAXONOMY_PATH)
        required = {
            "PERSONAL_DATA", "FINANCIAL_DATA", "TEMPORAL_DATA",
            "GEOGRAPHICAL_DATA", "BUSINESS_ENTITY_DATA", "CATEGORICAL_DATA",
            "QUANTITATIVE_DATA", "TEXTUAL_DATA", "TECHNICAL_DATA", "UNKNOWN_DATA",
        }
        found = set(result.stats.get("groups_found", []))
        assert required.issubset(found), f"Missing groups: {required - found}"

    def test_t03_all_expected_types_exist(self, loader):
        expected_types = [
            "EMAIL", "PHONE", "PERSON_NAME", "PERSON_ID", "AGE", "BIRTH_DATE",
            "PERSONAL_ADDRESS", "PRICE", "PAYMENT_AMOUNT", "REVENUE", "COST",
            "DISCOUNT", "TAX", "FREIGHT_COST", "PROFIT", "DATE", "DATETIME",
            "TIME", "YEAR", "MONTH", "DURATION", "PERIOD",
            "COUNTRY", "STATE", "CITY", "POSTAL_CODE", "LATITUDE", "LONGITUDE",
            "ORDER_ID", "PRODUCT_ID", "SELLER_ID", "INVOICE_ID", "TRANSACTION_ID",
            "STATUS", "PRODUCT_CATEGORY", "PAYMENT_METHOD", "BOOLEAN_FLAG",
            "QUANTITY", "WEIGHT", "LENGTH", "PERCENTAGE", "RATING",
            "DESCRIPTION", "COMMENT", "TITLE", "FREE_TEXT",
            "SYSTEM_ID", "HASH_VALUE", "VERSION", "FILE_REFERENCE",
            "UNKNOWN",
        ]
        for tid in expected_types:
            assert loader.is_valid_type(tid), f"Missing type: {tid}"

    def test_t04_type_ids_are_unique(self, raw_data):
        all_ids = []
        for g in raw_data["groups"]:
            for t in g.get("types", []):
                all_ids.append(t["type_id"])
        assert len(all_ids) == len(set(all_ids)), f"Duplicate type_ids: {[x for x in all_ids if all_ids.count(x) > 1]}"

    def test_t05_all_types_have_descriptions(self, raw_data):
        for g in raw_data["groups"]:
            for t in g.get("types", []):
                assert t.get("description"), f"Type {t['type_id']} has no description"

    def test_t06_version_exists(self, raw_data):
        assert raw_data.get("taxonomy_version") == "1.1.1"

    def test_t06b_upper_snake_case(self, raw_data):
        for g in raw_data["groups"]:
            assert g["group_id"] == g["group_id"].upper(), f"Group {g['group_id']} not UPPER_SNAKE_CASE"
            for t in g.get("types", []):
                assert t["type_id"] == t["type_id"].upper(), f"Type {t['type_id']} not UPPER_SNAKE_CASE"


# ── T07-T12: Loader API ─────────────────────────────────────────────────
class TestLoaderAPI:
    def test_t07_loader_summary(self, loader):
        s = loader.summary()
        assert s["total_groups"] >= 10
        assert s["total_types"] >= 60

    def test_t08_valid_pair_accepted(self, loader):
        assert loader.is_valid_pair("PERSONAL_DATA", "EMAIL")
        assert loader.is_valid_pair("FINANCIAL_DATA", "PRICE")
        assert loader.is_valid_pair("UNKNOWN_DATA", "UNKNOWN")

    def test_t09_invalid_pair_rejected(self, loader):
        assert not loader.is_valid_pair("FINANCIAL_DATA", "EMAIL")
        assert not loader.is_valid_pair("PERSONAL_DATA", "PRICE")
        assert not loader.is_valid_pair("FAKE_GROUP", "EMAIL")

    def test_t10_alias_resolution(self, loader):
        assert loader.type_id_from_alias("customer_email") == "EMAIL"
        assert loader.type_id_from_alias("payment_value") == "PAYMENT_AMOUNT"
        assert loader.type_id_from_alias("order_purchase_timestamp") == "DATETIME"
        assert loader.type_id_from_alias("product_weight_g") == "WEIGHT"

    def test_t11_privacy_hints(self, loader):
        # Migrated to PrivacyHint enum values (taxonomy v1.1.1)
        assert loader.privacy_hint_for("EMAIL") == "LIKELY_PII"
        assert loader.privacy_hint_for("PRICE") == "NO_DIRECT_PII_INDICATOR"
        assert loader.privacy_hint_for("AGE") == "CONTEXT_DEPENDENT"
        assert loader.privacy_hint_for("UNKNOWN") == "NO_DIRECT_PII_INDICATOR"
        # PERSON_ID aligned with prompt spec: customer_id -> PERSON_ID -> POTENTIAL_PII
        assert loader.privacy_hint_for("PERSON_ID") == "POTENTIAL_PII"

    def test_t12_group_for_type(self, loader):
        assert loader.group_for_type("EMAIL") == "PERSONAL_DATA"
        assert loader.group_for_type("PRICE") == "FINANCIAL_DATA"
        assert loader.group_for_type("DATE") == "TEMPORAL_DATA"
        assert loader.group_for_type("ORDER_ID") == "BUSINESS_ENTITY_DATA"
        assert loader.group_for_type("UNKNOWN") == "UNKNOWN_DATA"


# ── T13-T20: Validation & edge cases ────────────────────────────────────
class TestValidation:
    def test_t13_validate_valid_pair(self, raw_data):
        r = validate_group_type_pair("PERSONAL_DATA", "EMAIL", raw_data)
        assert r.valid

    def test_t14_validate_invalid_pair_wrong_group(self, raw_data):
        r = validate_group_type_pair("FINANCIAL_DATA", "EMAIL", raw_data)
        assert not r.valid
        assert "does not belong" in r.errors[0]

    def test_t15_validate_unknown_group(self, raw_data):
        r = validate_group_type_pair("FAKE_GROUP", "EMAIL", raw_data)
        assert not r.valid
        assert "Unknown group" in r.errors[0]

    def test_t16_validate_unknown_type(self, raw_data):
        r = validate_group_type_pair("PERSONAL_DATA", "FAKE_TYPE", raw_data)
        assert not r.valid
        assert "Unknown type" in r.errors[0]

    def test_t17_unknown_data_exists(self, loader):
        assert loader.is_valid_group("UNKNOWN_DATA")
        assert loader.is_valid_type("UNKNOWN")
        assert loader.is_valid_pair("UNKNOWN_DATA", "UNKNOWN")

    def test_t18_types_in_group(self, loader):
        personal = loader.types_in_group("PERSONAL_DATA")
        tids = [t.type_id for t in personal]
        assert "EMAIL" in tids
        assert "PHONE" in tids
        assert "PERSON_NAME" in tids

    def test_t19_nonexistent_file_detected(self, tmp_path):
        r = validate_taxonomy_file(tmp_path / "nonexistent.yaml")
        assert not r.valid
        assert "not found" in r.errors[0]

    def test_t20_extensibility(self, loader):
        """The taxonomy can grow without breaking existing lookups."""
        assert loader.is_valid_pair("PERSONAL_DATA", "EMAIL")
        assert loader.group_for_type("EMAIL") == "PERSONAL_DATA"
        # A non-existent type does not break anything
        assert loader.get_type("FUTURE_TYPE") is None
        assert loader.group_for_type("FUTURE_TYPE") is None


# ── Strict validation tests ─────────────────────────────────────────────
class TestStrictValidation:
    def test_missing_group_description_is_error(self, tmp_path):
        """A group with no description must cause valid=False."""
        yaml_content = (
            'taxonomy_version: "1.1.1"\n'
            "groups:\n"
            "  - group_id: PERSONAL_DATA\n"
            "    label: Personal Data\n"
            "    # description intentionally omitted\n"
            "    types:\n"
            "      - type_id: EMAIL\n"
            "        label: Email\n"
            "        description: Electronic mail address.\n"
            "        privacy_hint: LIKELY_PII\n"
            "        column_aliases: []\n"
            "        patterns: []\n"
        )
        bad_yaml = tmp_path / "bad_group_desc.yaml"
        bad_yaml.write_text(yaml_content, encoding="utf-8")
        result = validate_taxonomy_file(bad_yaml)
        assert not result.valid, "Expected valid=False when group description is missing"
        assert any("no description" in e.lower() or "PERSONAL_DATA" in e for e in result.errors)

    def test_missing_type_description_is_error(self, tmp_path):
        """A type with no description must cause valid=False."""
        yaml_content = (
            'taxonomy_version: "1.1.1"\n'
            "groups:\n"
            "  - group_id: PERSONAL_DATA\n"
            "    label: Personal Data\n"
            "    description: Group with personal data.\n"
            "    types:\n"
            "      - type_id: EMAIL\n"
            "        label: Email\n"
            "        # description intentionally omitted\n"
            "        privacy_hint: LIKELY_PII\n"
            "        column_aliases: []\n"
            "        patterns: []\n"
        )
        bad_yaml = tmp_path / "bad_type_desc.yaml"
        bad_yaml.write_text(yaml_content, encoding="utf-8")
        result = validate_taxonomy_file(bad_yaml)
        assert not result.valid, "Expected valid=False when type description is missing"
        assert any("EMAIL" in e and "description" in e.lower() for e in result.errors)

    def test_group_without_types_is_error(self, tmp_path):
        """A group with no types must cause valid=False."""
        yaml_content = (
            'taxonomy_version: "1.1.1"\n'
            "groups:\n"
            "  - group_id: PERSONAL_DATA\n"
            "    label: Personal Data\n"
            "    description: Group with personal data.\n"
            "    types: []\n"
        )
        bad_yaml = tmp_path / "bad_empty_group.yaml"
        bad_yaml.write_text(yaml_content, encoding="utf-8")
        result = validate_taxonomy_file(bad_yaml)
        assert not result.valid, "Expected valid=False when a group has no types"
        assert any("PERSONAL_DATA" in e and "no types" in e.lower() for e in result.errors)

    def test_invalid_privacy_hint_is_error(self, tmp_path):
        """A type with an unknown privacy_hint must cause valid=False."""
        yaml_content = (
            'taxonomy_version: "1.1.1"\n'
            "groups:\n"
            "  - group_id: PERSONAL_DATA\n"
            "    label: Personal Data\n"
            "    description: Group with personal data.\n"
            "    types:\n"
            "      - type_id: EMAIL\n"
            "        label: Email\n"
            "        description: Electronic mail address.\n"
            "        privacy_hint: HIGH\n"  # invalid value
            "        column_aliases: []\n"
            "        patterns: []\n"
        )
        bad_yaml = tmp_path / "bad_hint.yaml"
        bad_yaml.write_text(yaml_content, encoding="utf-8")
        result = validate_taxonomy_file(bad_yaml)
        assert not result.valid, "Expected valid=False when privacy_hint is invalid"
        assert any("HIGH" in e and "privacy_hint" in e.lower() for e in result.errors)

    def test_invalid_version_format_is_error(self, tmp_path):
        """taxonomy_version='abc' must cause valid=False."""
        yaml_content = (
            'taxonomy_version: "abc"\n'
            "groups:\n"
            "  - group_id: PERSONAL_DATA\n"
            "    label: Personal Data\n"
            "    description: Group with personal data.\n"
            "    types:\n"
            "      - type_id: EMAIL\n"
            "        label: Email\n"
            "        description: Electronic mail address.\n"
            "        privacy_hint: LIKELY_PII\n"
            "        column_aliases: []\n"
            "        patterns: []\n"
        )
        bad_yaml = tmp_path / "bad_version.yaml"
        bad_yaml.write_text(yaml_content, encoding="utf-8")
        result = validate_taxonomy_file(bad_yaml)
        assert not result.valid, "Expected valid=False when taxonomy_version is 'abc'"
        assert any("version" in e.lower() for e in result.errors)
