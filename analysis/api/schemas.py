"""Request and response bodies of Rabeb's routes that are not already contracts.
What the Analyst produces (AnalysisResult, AgentResult, KpiCatalog, Glossary...) is returned AS IS."""
from typing import Literal

from pydantic import BaseModel, Field

from contracts.agent import AgentResult
from contracts.analysis import AnalysisResult, Insight, ValidationCheck
from contracts.common import Period
from contracts.semantic import Glossary, KpiCatalog


class LlmInfo(BaseModel):
    provider: str
    model: str
    ready: bool                        # a key is present (or Ollama, which needs none)


class Health(BaseModel):
    status: str = "ok"
    contracts_version: str
    catalog_version: str
    kpis: int
    llm: LlmInfo


class RunAnalysis(BaseModel):
    llm: bool = Field(True, description="Insights written by the LLM agent (fact-checked); "
                                        "False = deterministic sentences")


class RunAnalysisResult(BaseModel):
    agent: AgentResult                 # status success / failed + message
    result: AnalysisResult | None      # None when the Analyst refused (unknown KPI, forbidden dimension)


class Insights(BaseModel):
    run_id: str
    source: Literal["llm", "fallback"] | None   # who wrote the sentences (from the audit journal)
    insights: list[Insight]


class ResultRows(BaseModel):
    """result.parquet as JSON: one row per (dimensions..., period), ready for a chart."""
    run_id: str
    columns: list[str]
    rows: list[dict]


class KpiPreview(BaseModel):
    run_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Run whose warehouse is used")
    metric: str = Field(..., description="KPI name in the catalog, e.g. 'Revenue'")
    dimensions: list[str] = []
    period: Period
    compare_to: Period | None = None


class KpiPreviewResult(BaseModel):
    kpi: str                           # "Revenue@2.0"
    unit: str
    sql: str
    rows: list[dict]
    validations: list[ValidationCheck]


class ProposeKpis(BaseModel):
    llm: bool = Field(True, description="Let the LLM choose and name the KPIs; False = every candidate")


class KpiProposal(BaseModel):
    """A DRAFT: nothing is written into kpi/catalog.yaml. A human reviews it before use."""
    run_id: str
    source: Literal["llm", "mechanical"]
    catalog: KpiCatalog
    glossary: Glossary
