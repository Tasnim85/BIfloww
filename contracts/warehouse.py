"""Step 3: the star schema in DuckDB, and the lineage graph. Owner: Ahmed.

WarehouseManifest       -> Rabeb (analysis), Tasnim (comparisons), Malek (request)
TransformationReceipts  -> Rabeb (join multiplicity check), Tasnim (grain), lineage
LineageGraph            -> Auditor, app ("where does this number come from?")
"""
from enum import Enum

from pydantic import Field

from contracts.common import Artifact, Contract


class TableKind(str, Enum):
    FACT = "fact"
    DIMENSION = "dimension"


class WarehouseTable(Contract):
    name: str                          # e.g. "fact_payments"
    kind: TableKind
    grain: str                         # what ONE row is, e.g. "payment", "order_item"
    primary_key: list[str]
    row_count: int
    columns: list[str]
    date_column: str | None = None     # main date of a fact table, e.g. "order_purchase_date"
    date_min: str | None = None        # ISO date: first day with data
    date_max: str | None = None        # ISO date: last day with data (coverage checks use it)


class WarehouseManifest(Artifact):
    database_file: str = "warehouse.duckdb"
    tables: list[WarehouseTable]


class TransformationReceipt(Contract):
    """One receipt per table built. Lets others check a join did not duplicate rows."""
    output_table: str                  # e.g. "fact_payments"
    source_tables: list[str]           # e.g. ["orders", "order_payments"]
    join_keys: list[str] = Field(default_factory=list)   # e.g. ["order_id"]
    rows_before: int                   # rows of the MAIN source table
    rows_after: int                    # rows of the output table
    grain: str                         # what one output row represents
    filters: list[str] = Field(default_factory=list)     # e.g. ["order_status == 'delivered'"]
    column_sources: dict[str, str] = Field(default_factory=dict)
    # output column -> "source_table.column" (lineage is built from this)


class TransformationReceipts(Artifact):
    receipts: list[TransformationReceipt]


class NodeKind(str, Enum):
    RAW_COLUMN = "raw_column"          # e.g. "order_payments.payment_value"
    TABLE = "table"
    TRANSFORMATION = "transformation"
    KPI = "kpi"


class LineageNode(Contract):
    id: str                            # unique, e.g. "kpi:Revenue@2.0"
    kind: NodeKind
    label: str


class LineageEdge(Contract):
    source: str                        # node id (upstream)
    target: str                        # node id (downstream)
    relation: str                      # e.g. "joined_on order_id", "filtered", "aggregated SUM"


class LineageGraph(Artifact):
    nodes: list[LineageNode]
    edges: list[LineageEdge]
