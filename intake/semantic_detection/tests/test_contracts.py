"""test_contracts.py — Tests for the proposed semantic Pydantic contracts.

Tests cover:
  C01-C05: SemanticColumn instantiation, validation, JSON round-trip
  C06-C10: SemanticMetadata counters, validation errors
  C11-C15: SemanticMatch, SemanticMatchesReport, edge cases
  C16-C20: Privacy hints, evidence, optional fields, compatibility
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.proposals.semantic_contracts import (
    ClassificationStatus,
    PrivacyHint,
    RelationshipType,
    SemanticColumn,
    SemanticMatch,
    SemanticMatchesReport,
    SemanticMetadata,
)


# ── C01-C05: SemanticColumn ──────────────────────────────────────────────
class TestSemanticColumn:
    def test_c01_valid_column(self):
        col = SemanticColumn(
            source_table="olist_customers",
            column_name="customer_email",
            technical_type="object",
            semantic_group="PERSONAL_DATA",
            semantic_type="EMAIL",
            privacy_hint=PrivacyHint.POTENTIAL_PII,
            classification_status=ClassificationStatus.MANUAL_REFERENCE,
            evidence=["Column name contains 'email'", "Pandas dtype: object"],
        )
        assert col.semantic_type == "EMAIL"
        assert col.privacy_hint == PrivacyHint.POTENTIAL_PII

    def test_c02_empty_table_rejected(self):
        with pytest.raises(Exception):
            SemanticColumn(
                source_table="",
                column_name="email",
                semantic_group="PERSONAL_DATA",
                semantic_type="EMAIL",
            )

    def test_c03_empty_column_rejected(self):
        with pytest.raises(Exception):
            SemanticColumn(
                source_table="table",
                column_name="",
                semantic_group="PERSONAL_DATA",
                semantic_type="EMAIL",
            )

    def test_c04_json_roundtrip(self):
        col = SemanticColumn(
            source_table="orders",
            column_name="order_id",
            semantic_group="BUSINESS_ENTITY_DATA",
            semantic_type="ORDER_ID",
            classification_status=ClassificationStatus.MANUAL_REFERENCE,
        )
        json_str = col.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["semantic_type"] == "ORDER_ID"
        # Reconstruct
        col2 = SemanticColumn.model_validate_json(json_str)
        assert col2.column_name == "order_id"

    def test_c05_confidence_bounds(self):
        with pytest.raises(Exception):
            SemanticColumn(
                source_table="t", column_name="c",
                semantic_group="PERSONAL_DATA", semantic_type="EMAIL",
                confidence_score=1.5,  # out of [0, 1]
            )

    def test_c05_mismatched_pair_rejected(self):
        """FINANCIAL_DATA / EMAIL must be rejected by Pydantic validator."""
        with pytest.raises(ValueError, match="does not belong"):
            SemanticColumn(
                source_table="orders", column_name="email",
                semantic_group="FINANCIAL_DATA", semantic_type="EMAIL",
            )

    def test_c05_fake_group_rejected(self):
        """FAKE_GROUP must be rejected by Pydantic validator."""
        with pytest.raises(ValueError, match="Unknown semantic_group"):
            SemanticColumn(
                source_table="orders", column_name="col",
                semantic_group="FAKE_GROUP", semantic_type="EMAIL",
            )

    def test_c05b_no_confidence_for_manual(self):
        col = SemanticColumn(
            source_table="t", column_name="c",
            semantic_group="PERSONAL_DATA", semantic_type="EMAIL",
            classification_status=ClassificationStatus.MANUAL_REFERENCE,
            confidence_score=None,
        )
        assert col.confidence_score is None

    def test_c05c_evidence_no_raw_emails(self):
        with pytest.raises(Exception):
            SemanticColumn(
                source_table="t", column_name="c",
                semantic_group="PERSONAL_DATA", semantic_type="EMAIL",
                evidence=["Sample: john@example.com"],
            )


# ── C06-C10: SemanticMetadata ────────────────────────────────────────────
class TestSemanticMetadata:
    def _make_columns(self):
        return [
            SemanticColumn(
                source_table="orders", column_name="order_id",
                semantic_group="BUSINESS_ENTITY_DATA", semantic_type="ORDER_ID",
                classification_status=ClassificationStatus.MANUAL_REFERENCE,
            ),
            SemanticColumn(
                source_table="orders", column_name="order_status",
                semantic_group="CATEGORICAL_DATA", semantic_type="STATUS",
                classification_status=ClassificationStatus.MANUAL_REFERENCE,
            ),
            SemanticColumn(
                source_table="orders", column_name="mystery_col",
                semantic_group="UNKNOWN_DATA", semantic_type="UNKNOWN",
                review_required=True,
                classification_status=ClassificationStatus.UNKNOWN,
            ),
        ]

    def test_c06_valid_report(self):
        cols = self._make_columns()
        report = SemanticMetadata(
            dataset_name="olist_orders",
            columns=cols,
            total_columns=3,
            classified_columns=2,
            unknown_columns=1,
            review_required_columns=1,
        )
        assert report.total_columns == 3

    def test_c07_wrong_total_rejected(self):
        cols = self._make_columns()
        with pytest.raises(Exception):
            SemanticMetadata(
                dataset_name="olist",
                columns=cols,
                total_columns=99,  # wrong
                classified_columns=2,
                unknown_columns=1,
                review_required_columns=1,
            )

    def test_c08_wrong_unknown_count_rejected(self):
        cols = self._make_columns()
        with pytest.raises(Exception):
            SemanticMetadata(
                dataset_name="olist",
                columns=cols,
                total_columns=3,
                classified_columns=2,
                unknown_columns=0,  # wrong: there's 1 UNKNOWN
                review_required_columns=1,
            )

    def test_c09_json_roundtrip(self):
        cols = self._make_columns()
        report = SemanticMetadata(
            dataset_name="olist",
            columns=cols,
            total_columns=3,
            classified_columns=2,
            unknown_columns=1,
            review_required_columns=1,
        )
        json_str = report.model_dump_json(indent=2)
        report2 = SemanticMetadata.model_validate_json(json_str)
        assert report2.total_columns == 3
        assert len(report2.columns) == 3

    def test_c10_empty_report(self):
        report = SemanticMetadata(
            dataset_name="empty",
            columns=[],
            total_columns=0,
            classified_columns=0,
            unknown_columns=0,
            review_required_columns=0,
        )
        assert report.total_columns == 0

    def test_c10_empty_columns_with_nonzero_total_rejected(self):
        """columns=[] with total_columns=99 must be rejected."""
        with pytest.raises(ValueError, match="total_columns"):
            SemanticMetadata(
                dataset_name="empty",
                columns=[],
                total_columns=99,
                classified_columns=0,
                unknown_columns=0,
                review_required_columns=0,
            )


# ── C11-C15: SemanticMatch & MatchesReport ───────────────────────────────
class TestSemanticMatch:
    def test_c11_valid_match(self):
        m = SemanticMatch(
            source_table="orders", source_column="customer_id",
            target_table="customers", target_column="customer_id",
            relationship_type=RelationshipType.SAME_CONCEPT_CANDIDATE,
            similarity_score=None,
            evidence=["Same column name across tables"],
        )
        assert m.relationship_type == RelationshipType.SAME_CONCEPT_CANDIDATE

    def test_c12_match_json_roundtrip(self):
        m = SemanticMatch(
            source_table="a", source_column="x",
            target_table="b", target_column="y",
        )
        json_str = m.model_dump_json()
        m2 = SemanticMatch.model_validate_json(json_str)
        assert m2.source_table == "a"

    def test_c13_matches_report(self):
        report = SemanticMatchesReport(
            method="not_implemented",
            matches=[],
            total_comparisons=0,
            matches_found=0,
        )
        assert report.matches_found == 0

    def test_c14_matches_count_mismatch(self):
        m = SemanticMatch(
            source_table="a", source_column="x",
            target_table="b", target_column="y",
        )
        with pytest.raises(Exception):
            SemanticMatchesReport(
                matches=[m],
                matches_found=5,  # wrong
            )

    def test_c15b_empty_matches_with_nonzero_count_rejected(self):
        """matches=[] with matches_found=99 must be rejected."""
        with pytest.raises(ValueError, match="matches_found"):
            SemanticMatchesReport(
                matches=[],
                matches_found=99,
            )

    def test_c15_similarity_score_bounds(self):
        with pytest.raises(Exception):
            SemanticMatch(
                source_table="a", source_column="x",
                target_table="b", target_column="y",
                similarity_score=2.0,  # out of [0, 1]
            )


# ── C16-C20: Privacy, compatibility, optional fields ────────────────────
class TestPrivacyAndCompatibility:
    def test_c16_privacy_hint_enum(self):
        assert PrivacyHint.POTENTIAL_PII.value == "POTENTIAL_PII"
        assert PrivacyHint.NO_DIRECT_PII_INDICATOR.value == "NO_DIRECT_PII_INDICATOR"

    def test_c17_classification_status_enum(self):
        assert ClassificationStatus.MANUAL_REFERENCE.value == "MANUAL_REFERENCE"
        assert ClassificationStatus.AUTOMATIC.value == "AUTOMATIC"

    def test_c18_optional_fields_default(self):
        col = SemanticColumn(
            source_table="t", column_name="c",
            semantic_group="UNKNOWN_DATA", semantic_type="UNKNOWN",
        )
        assert col.confidence_score is None
        assert col.classifier_version is None
        assert col.business_concept_candidate is None
        assert col.semantic_role is None

    def test_c19_no_personal_data_in_examples(self):
        """Evidence fields must not contain raw personal data."""
        col = SemanticColumn(
            source_table="t", column_name="c",
            semantic_group="PERSONAL_DATA", semantic_type="EMAIL",
            evidence=["Column name contains keyword 'email'"],
        )
        for e in col.evidence:
            assert "@" not in e or "example" not in e.lower()

    def test_c20_contracts_import_from_common(self):
        """Verify our contracts inherit from the shared base classes."""
        from contracts.common import Artifact, Contract
        assert issubclass(SemanticColumn, Contract)
        assert issubclass(SemanticMetadata, Artifact)
        assert issubclass(SemanticMatchesReport, Artifact)
