"""Provisional local artifacts; replace with contracts/warehouse.py when supplied."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Count = Annotated[int, Field(ge=0)]


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str


class WarehouseTable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: Count
    grain: str
    primary_key: list[str]
    columns: list[Column]
    physical_sources: dict[str, list[str]] = Field(default_factory=dict)
    kind: Literal["table", "view"] = "table"


class Reconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payments_source: str
    payments_warehouse: str


class WarehouseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    warehouse: str
    tables: dict[str, WarehouseTable]
    reconciliation: Reconciliation
    revenue_catalog_status: Literal["owned_by_Rabeb_not_defined_here"]
    schema_type: Literal["star", "snowflake", "constellation"] = "constellation"
    schema_selection: Literal["llm", "explicit"] = "explicit"
    schema_recommendation: str | None = None
    physical_tables: dict[str, WarehouseTable] = Field(default_factory=dict)


class LineageNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["raw", "pii", "clean", "warehouse", "physical", "kpi", "transformation"]


class LineageEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    operation: str


class LineageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["bo2-local-1"] = "bo2-local-1"
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    catalog_validated: Literal[False] = False
