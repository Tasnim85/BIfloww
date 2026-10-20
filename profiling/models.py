"""Provisional local artifacts; replace with contracts/quality.py when supplied."""
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


class AnomalyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    table: Literal["order_payments"]
    features: list[str]
    rows: Count
    flagged: Count
    seed: int
    policy: Literal["flag_only_never_delete"]
