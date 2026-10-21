"""Private BO2 classification details; shared files use contracts.privacy."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Count = Annotated[int, Field(ge=0)]


class MaskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    column: str
    action: Literal["keep", "hmac_sha256", "redact_text", "generalize_zip", "generalize_coordinate", "redact_detected_pii"]
    non_null_rows: Count
    semantic_type: str | None = None
    confidence: float | None = None
    classification_source: Literal["llm", "contact_guardrail", "key_group", "shared_key_name"] | None = None


class PiiReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    column: str
    reason: Literal["unknown_type", "low_confidence", "invalid_coordinate"]


class PiiReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    policy_version: str
    pseudonymized_not_anonymous: bool = True
    tables: dict[str, Count]
    decisions: list[MaskDecision]
    model: str | None = None
    classification: list[MaskDecision] = Field(default_factory=list)
    needs_review: list[PiiReview] = Field(default_factory=list)
    uncertainty_policy: Literal["review", "redact"] = "review"
    uncertain_columns: list[PiiReview] = Field(default_factory=list)
    prompt_version: str | None = None
    prompt_sha256: str | None = None
