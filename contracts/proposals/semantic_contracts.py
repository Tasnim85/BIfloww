"""Proposed semantic contracts for Step 1a (Malek).

These models extend the shared contracts without modifying them.
Once validated by the team, they can be moved into contracts/.

Compatibility:
  - Inherits from contracts.common.Contract and contracts.common.Artifact
  - Uses contracts.common.SemanticType enum for the simplified type
  - Adds rich metadata (group, privacy_hint, evidence, confidence)

These contracts do NOT implement PII masking, cleaning, profiling or ETL.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

# Import the shared base classes — never modify them
from contracts.common import Artifact, Contract


# ── Enumerations ─────────────────────────────────────────────────────────
class PrivacyHint(str, Enum):
    """Indicates a column MAY contain sensitive data. Not a PII decision."""
    NO_DIRECT_PII_INDICATOR = "NO_DIRECT_PII_INDICATOR"
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"
    POTENTIAL_PII = "POTENTIAL_PII"
    LIKELY_PII = "LIKELY_PII"


class ClassificationStatus(str, Enum):
    """How a classification was produced."""
    MANUAL_REFERENCE = "MANUAL_REFERENCE"      # human-annotated ground truth
    AUTOMATIC = "AUTOMATIC"                     # classified by the model
    NEEDS_REVIEW = "NEEDS_REVIEW"              # low confidence, needs human check
    UNKNOWN = "UNKNOWN"                         # could not be classified


class RelationshipType(str, Enum):
    """Future BO1-06: relationship between two columns."""
    SAME_CONCEPT_CANDIDATE = "SAME_CONCEPT_CANDIDATE"
    SAME_SEMANTIC_TYPE = "SAME_SEMANTIC_TYPE"
    RELATED_CONCEPT = "RELATED_CONCEPT"
    NO_RELEVANT_MATCH = "NO_RELEVANT_MATCH"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# ── SemanticColumn ───────────────────────────────────────────────────────
class SemanticColumn(Contract):
    """Rich semantic metadata for a single column.

    This is the detailed view. The simplified ColumnType in contracts.intake
    has just (table, column, semantic_type, confidence, pii_candidate).
    This model adds group, privacy_hint, evidence and classification status.
    """
    # Identity
    source_table: str = Field(..., min_length=1, description="Table this column belongs to.")
    column_name: str = Field(..., min_length=1, description="Column name as it appears in the schema.")
    technical_type: str = Field(default="object", description="Pandas dtype or SQL type.")

    # Classification
    semantic_group: str = Field(..., description="Top-level group from taxonomy (e.g. PERSONAL_DATA).")
    semantic_type: str = Field(..., description="Specific type from taxonomy (e.g. EMAIL).")
    semantic_role: str | None = Field(
        default=None,
        description="Optional functional role (IDENTIFIER, MEASURE, DIMENSION, ATTRIBUTE)."
    )

    # Business glossary link (Rabeb's domain — just a pointer)
    business_concept_candidate: str | None = Field(
        default=None,
        description="Candidate term from Rabeb's glossary, e.g. 'Revenue'. Set by future integration."
    )

    # Privacy indicator (for Ikbel — NOT a PII decision)
    privacy_hint: PrivacyHint = Field(
        default=PrivacyHint.NO_DIRECT_PII_INDICATOR,
        description="Hint for the PII agent. Does NOT replace Ikbel's PII detection."
    )

    # Confidence
    confidence_score: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Classification confidence [0, 1]. None for manual annotations."
    )
    confidence_method: str | None = Field(
        default=None,
        description="How confidence was computed (e.g. 'rule_based', 'embedding_cosine')."
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Non-sensitive metadata explaining the classification."
    )

    # Status
    review_required: bool = Field(default=False, description="True if a human should review.")
    classification_status: ClassificationStatus = Field(
        default=ClassificationStatus.UNKNOWN,
        description="How this classification was produced."
    )
    classifier_version: str | None = Field(
        default=None,
        description="Version of the classifier that produced this. None for manual."
    )

    @field_validator("evidence")
    @classmethod
    def evidence_no_raw_values(cls, v: list[str]) -> list[str]:
        """Evidence must NOT contain raw personal data values."""
        for item in v:
            lower = item.lower()
            if "@" in lower and "." in lower.split("@")[-1]:
                raise ValueError(
                    f"Evidence must not contain raw personal data (possible email found)."
                )
        return v


# ── SemanticMetadata (full report) ───────────────────────────────────────
class SemanticMetadata(Artifact):
    """Complete semantic classification report for a dataset.

    This is the rich report. The pipeline outputs the simplified
    ColumnTypesReport (contracts.intake) for downstream agents.
    This report is saved alongside for documentation and debugging.
    """
    schema_version: str = Field(default="1.0.0", description="Version of this report schema.")
    taxonomy_version: str = Field(default="1.0.0", description="Version of the taxonomy used.")
    run_id: str = Field(default="", description="Pipeline run identifier.")
    dataset_name: str = Field(default="", description="Name of the classified dataset.")
    columns: list[SemanticColumn] = Field(default_factory=list, description="Classified columns.")

    # Computed counters
    total_columns: int = Field(default=0, description="Total number of columns.")
    classified_columns: int = Field(default=0, description="Columns with a known type.")
    unknown_columns: int = Field(default=0, description="Columns classified as UNKNOWN.")
    review_required_columns: int = Field(default=0, description="Columns needing human review.")

    @model_validator(mode="after")
    def check_counters(self) -> "SemanticMetadata":
        """Ensure counters match the actual column list."""
        if self.columns:
            expected_total = len(self.columns)
            expected_unknown = sum(
                1 for c in self.columns if c.semantic_type == "UNKNOWN"
            )
            expected_review = sum(1 for c in self.columns if c.review_required)
            expected_classified = expected_total - expected_unknown

            if self.total_columns != expected_total:
                raise ValueError(
                    f"total_columns ({self.total_columns}) != len(columns) ({expected_total})"
                )
            if self.unknown_columns != expected_unknown:
                raise ValueError(
                    f"unknown_columns ({self.unknown_columns}) != actual ({expected_unknown})"
                )
            if self.classified_columns != expected_classified:
                raise ValueError(
                    f"classified_columns ({self.classified_columns}) != actual ({expected_classified})"
                )
            if self.review_required_columns != expected_review:
                raise ValueError(
                    f"review_required_columns ({self.review_required_columns}) != actual ({expected_review})"
                )
        return self


# ── Future BO1-06: Semantic Match contracts ──────────────────────────────
class SemanticMatch(Contract):
    """A potential semantic relationship between two columns.

    Prepared for BO1-06 Semantic Similarity Detection.
    The similarity_score computation is NOT implemented in Step 1.
    """
    source_table: str = Field(..., min_length=1)
    source_column: str = Field(..., min_length=1)
    target_table: str = Field(..., min_length=1)
    target_column: str = Field(..., min_length=1)
    relationship_type: RelationshipType = Field(
        default=RelationshipType.NEEDS_REVIEW,
        description="Nature of the semantic relationship."
    )
    similarity_score: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Similarity score [0, 1]. None until the similarity engine is built."
    )
    evidence: list[str] = Field(default_factory=list)
    review_required: bool = Field(default=True)


class SemanticMatchesReport(Artifact):
    """Report of all semantic matches found between columns/datasets.

    Prepared for BO1-06. The matching engine is NOT implemented in Step 1.
    """
    schema_version: str = Field(default="1.0.0")
    taxonomy_version: str = Field(default="1.0.0")
    run_id: str = Field(default="")
    method: str = Field(default="not_implemented", description="Matching method used.")
    threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Minimum similarity threshold.")
    matches: list[SemanticMatch] = Field(default_factory=list)
    total_comparisons: int = Field(default=0)
    matches_found: int = Field(default=0)

    @model_validator(mode="after")
    def check_match_count(self) -> "SemanticMatchesReport":
        if self.matches and self.matches_found != len(self.matches):
            raise ValueError(
                f"matches_found ({self.matches_found}) != len(matches) ({len(self.matches)})"
            )
        return self
