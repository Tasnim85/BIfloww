"""Private BO2 diagnostics and SHAP metadata; shared files use contracts.quality."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Count = Annotated[int, Field(ge=0)]


class ColumnProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dtype: str
    missing: Count
    distinct: Count


class TableProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: Count
    duplicate_rows: Count
    columns: dict[str, ColumnProfile]


class ProfileReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    tables: dict[str, TableProfile]
    source_fingerprints: dict[str, str] = Field(default_factory=dict)


class AnomalyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    table: str
    features: list[str]
    rows: Count
    flagged: Count
    seed: int
    policy: Literal["flag_only_never_delete"]

    model_type: str = "IsolationForest"
    n_estimators: Count = 100
    contamination: float = Field(default=0.01, gt=0, le=0.5)
    model_flagged: Count = 0
    invalid_amount_rows: Count = 0
    invalid_feature_rows: Count = 0
    id_column: str | None = None
    amount_column: str | None = None
    score_definition: str = ""
    decision_offset: float = 0
    missing_per_feature: dict[str, Count] = Field(default_factory=dict)
    imputation: dict = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    model_sha256: str = ""
    scores_sha256: str = ""
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    shap: dict = Field(default_factory=dict)


class DayCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str | None
    orders: Count


class StatusCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None
    orders: Count


class DayStatusCount(DayCount):
    status: str | None


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    source_table: str
    date_column: str
    status_column: str
    id_column: str | None
    grain: Literal["order_id", "input_row"]
    total_orders: Count
    time_zone: Literal["UTC"]
    period_start: str | None
    period_end: str | None
    missing_dates: Count
    invalid_dates: Count
    missing_statuses: Count
    orders_by_day: list[DayCount]
    orders_by_status: list[StatusCount]
    orders_by_day_status: list[DayStatusCount]
