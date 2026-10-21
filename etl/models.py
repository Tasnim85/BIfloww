"""Private BO2 metadata and historical readers; shared files use contracts.warehouse."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

LINEAGE_VERSION = "2.1"

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
    reconciliation: Reconciliation | None
    revenue_catalog_status: Literal["owned_by_Rabeb_not_defined_here"]
    schema_type: Literal["star", "snowflake", "constellation", "single_table", "related_tables", "separate_tables", "analytical_flat", "relational"] = "constellation"
    schema_selection: Literal["llm", "explicit"] = "explicit"
    schema_recommendation: str | None = None
    physical_tables: dict[str, WarehouseTable] = Field(default_factory=dict)
    cleaning_source: str | None = None
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    source_tables: dict[str, str] = Field(default_factory=dict)
    relationships: list[dict] = Field(default_factory=list)
    table_roles: dict[str, str] = Field(default_factory=dict)
    quality_checks: dict[str, bool] = Field(default_factory=dict)
    approval_digest: str | None = None
    modeling_version: int = 1
    schema_rationale: str | None = None
    dimensional_links: list[dict] = Field(default_factory=list)
    column_sources: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    source_row_counts: dict[str, int] = Field(default_factory=dict)
    measure_bindings: dict[str, list[dict]] = Field(default_factory=dict)
    source_storage_tables: dict[str, WarehouseTable] = Field(default_factory=dict)
    # Views published in the shared manifest (etl/analytics.py).
    analytic_views: list[dict] = Field(default_factory=list)
    analytic_receipts: list[dict] = Field(default_factory=list)


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
    lineage_version: str = LINEAGE_VERSION
    graph_run_id: str | None = None
    etl_source: str | None = None
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    integration_status: Literal["bo2_only", "kpi_bindings_provided"] = "bo2_only"
