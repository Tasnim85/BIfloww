"""Request and response bodies of the API that are not already contracts.

Everything the agents produce is returned AS IS, with its contract (ComparisonReport,
ExplanationReport, WhyAnswer, DriftReport, JournalEntry...): the API adds no business field.
"""
from typing import Literal

from pydantic import BaseModel, Field

from contracts.audit import IntegrityReport
from contracts.common import Period
from contracts.comparisons import ComparisonReport, FixMethod, UserDecision
from contracts.semantic import AnalysisRequest
from contracts.xai import AnomalyExplanation


class LlmInfo(BaseModel):
    provider: str
    model: str
    ready: bool                        # a key is present (or Ollama, which needs none)


class Health(BaseModel):
    status: str = "ok"
    contracts_version: str
    llm: LlmInfo
    runs: int
    journals: list[str]


class RunInfo(BaseModel):
    run_id: str
    base_run: str                      # the run whose data it uses (itself, except custom comparisons)
    journal: str | None                # id of the journal holding its decisions
    has: dict[str, bool]               # request, comparison, anomalies, explanations, drift


class DashboardState(BaseModel):
    periods_source: str                # fix:<method> | as_asked | as_asked_by_user | waiting_for_user
    period: Period | None
    compare_to: Period | None


class DatasetKpi(BaseModel):
    name: str
    ref: str
    unit: str
    description: str
    allowed_dimensions: list[str]


class Dataset(BaseModel):
    """A run whose data (coverage profile + warehouse + catalog) can answer new questions."""
    run_id: str
    first_day: str
    last_day: str
    kpis: list[DatasetKpi]
    dimensions: dict[str, str]        # name -> description


class RunSummary(BaseModel):
    """Everything the result screen needs in ONE call."""
    run_id: str
    base_run: str
    journal: str | None
    request: AnalysisRequest | None
    comparison: ComparisonReport | None
    dashboard: DashboardState | None
    integrity: IntegrityReport | None
    anomalies: int | None
    drift_status: str | None


class Decision(BaseModel):
    decision: UserDecision
    chosen_fix: FixMethod | None = Field(None, description="Only with 'accepted'. Default: the recommended fix.")


class NewComparison(BaseModel):
    base_run: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Run whose data is used")
    metric: str = Field(..., description="KPI name in the catalog, e.g. 'Revenue'")
    dimensions: list[str] = []
    filters: list[str] = []
    period: Period
    compare_to: Period
    question: str = "Comparison typed in the app"
    llm: bool = Field(False, description="Summary written by the LLM (fact-checked)")
    lang: Literal["fr", "en"] | None = Field(None, description="Language of the texts (default: ?lang / Accept-Language / fr)")


class NewComparisonResult(BaseModel):
    run_id: str
    report: ComparisonReport


class ExplanationPage(BaseModel):
    run_id: str
    model_version: str
    explainer: str
    total: int
    offset: int
    items: list[AnomalyExplanation]


class WhyQuestion(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    lang: Literal["fr", "en"] | None = Field(None, description="Language of the answer (default: the question's)")


class JournalInfo(BaseModel):
    id: str
    label: str
    entries: int
    runs: list[str]
    intact: bool
