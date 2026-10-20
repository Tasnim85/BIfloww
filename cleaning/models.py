"""Provisional local artifacts; replace with contracts/quality.py when supplied."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Count = Annotated[int, Field(ge=0)]


class RowChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    rows_before: Count
    rows_after: Count
    removed_exact_duplicates: Count


class RuleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    column: str
    action: str


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    table: str | None = None
    column: str | None = None
    rows: Count | None = None
    proposal: str | None = None
    metadata: dict | None = None


class CleaningReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    selection: Literal["existing", "generated"] = "existing"
    playbook_path: str | None = None
    playbook_version: str
    changes: list[RowChange | RuleChange]
    needs_review: list[ReviewItem]
