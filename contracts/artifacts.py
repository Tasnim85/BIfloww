"""Contract 3: the shape of files passed between agents.

Only the files that more than one person reads need a contract. Two examples:
"""
from pydantic import BaseModel, Field


class TransformationReceipt(BaseModel):
    """Written by the ETL agent (Ahmed), read by KPI validation (Rabeb) and the Auditor (Tasnim)."""
    output_table: str                  # e.g. "fact_payments"
    source_tables: list[str]           # e.g. ["orders", "order_items"]
    join_keys: list[str] = Field(default_factory=list)  # e.g. ["order_id"]
    rows_before: int                   # rows in the main source table
    rows_after: int                    # rows after the transformation
    grain: str                         # what one output row represents, e.g. "order", "order_item"
    filters: list[str] = Field(default_factory=list)    # e.g. ["order_status == 'delivered'"]


class AnalysisRequest(BaseModel):
    """Written by request understanding (Malek), read by the Analyst (Rabeb) and comparisons (Tasnim)."""
    question: str                      # the user's words
    metric: str                        # KPI name from the catalog, e.g. "Revenue"
    dimensions: list[str] = Field(default_factory=list)  # e.g. ["customer_state"]
    period_start: str                  # ISO date
    period_end: str
    compare_to: tuple[str, str] | None = None             # optional previous period
    filters: list[str] = Field(default_factory=list)
