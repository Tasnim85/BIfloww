"""Step 6: dashboard spec. Owner: Samar. Read by: the Streamlit app, Auditor.

The spec describes the dashboard; the app draws it. Keeping them apart lets the
Auditor explain WHY a chart type was chosen.
"""
from enum import Enum

from pydantic import Field

from contracts.common import Artifact, Contract


class ChartType(str, Enum):
    KPI_CARD = "kpi_card"
    BAR = "bar"
    LINE = "line"
    MAP = "map"
    PIE = "pie"
    TABLE = "table"


class ChartSpec(Contract):
    chart_id: str
    chart_type: ChartType
    title: str
    data_file: str                     # parquet path, relative to runs/<run_id>/
    x: str | None = None
    y: str | None = None
    color: str | None = None
    reason: str                        # why this chart type (BO4 backup: automatic choice)


class DashboardSpec(Artifact):
    title: str
    question: str
    kpi: str                           # "Revenue@2.0"
    charts: list[ChartSpec]
    warnings: list[str] = Field(default_factory=list)   # copied from the comparison report
