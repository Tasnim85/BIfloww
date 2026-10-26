"""Side-car artifact: WHY each chart was chosen and what was found misleading.

DashboardSpec / ChartSpec (contracts/dashboard.py) stay untouched. This file is extra
evidence for the Auditor and the UI, written next to dashboard_spec.json.
"""
from enum import Enum

from pydantic import Field

from contracts.common import Artifact, Contract
from contracts.comparisons import CheckStatus
from contracts.dashboard import ChartType


class IssueKind(str, Enum):
    REQUESTED_CHART_REFUSED = "requested_chart_refused"
    TOO_MANY_CATEGORIES = "too_many_categories"
    DOMINANT_CATEGORY = "dominant_category"
    SAME_LEVEL = "same_level"
    TIME_GAP = "time_gap"
    BASE_EFFECT = "base_effect"
    MIXED_UNITS = "mixed_units"
    COMPARISON_BLOCKED = "comparison_blocked"
    COMPARISON_WARNING = "comparison_warning"
    COMPARISON_ADJUSTED = "comparison_adjusted"
    DATA_MISMATCH = "data_mismatch"


class VisualIssue(Contract):
    kind: IssueKind
    status: CheckStatus                # warning = shown next to the chart, blocking = chart changed
    message: str
    evidence: dict = Field(default_factory=dict)


class ChartCandidate(Contract):
    chart_type: ChartType
    score: float
    eligible: bool
    reasons: list[str]                 # why it fits, or why it was rejected


class ChartDecision(Contract):
    chart_id: str
    chosen: ChartType
    intent: str
    requested: ChartType | None = None
    candidates: list[ChartCandidate]   # all the types considered, best first
    issues: list[VisualIssue] = Field(default_factory=list)


class ChartAdvice(Artifact):
    rules_version: str
    comparison_shown: bool             # False: the comparison was held back (blocking check)
    decisions: list[ChartDecision]
