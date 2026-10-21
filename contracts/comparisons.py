"""Step 6 checks: misleading-comparison detection (BO4-12). Owner: Tasnim.
Read by: dashboard (Samar) to show the warning, Auditor.

The request is already clear (BO4-06 interpreted it). This step NEVER changes the
metric or the dimensions. It only judges whether the two periods are comparable
and, if not, PROPOSES a justified adjustment of period, population or scale.
Nothing is applied without the user's confirmation:
if a check is BLOCKING, the agent returns NEEDS_REVIEW, the app asks Sarra,
and writes her answer in user_decision / chosen_fix.

Inputs (by responsibility, as in the BO4-12 definition):
  DQ  -> profiling/coverage_profile.json   completeness per day
  SEM -> kpi/catalog.yaml                  unit, grain, filters, population
  ANA -> analysis/analysis_result.json     the values being compared
"""
from enum import Enum

from pydantic import Field

from contracts.common import Artifact, Contract, Period


class CheckKind(str, Enum):
    COVERAGE = "coverage"        # PERIODS: one period has incomplete days (partial month)
    POPULATION = "population"    # POPULATIONS: not the same filters / scope / customers
    UNIT = "unit"                # SCALES: not the same unit (BRL vs USD, count vs %)
    SCALE = "scale"              # SCALES: periods of different length, total vs average
    GRAIN = "grain"              # AGGREGATION LEVEL: one row = order vs order item


class CheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"          # show it, the comparison stays
    BLOCKING = "blocking"        # do not show the comparison as is


class ComparisonCheck(Contract):
    kind: CheckKind
    status: CheckStatus
    message: str                       # plain sentence for Sarra
    evidence: dict = Field(default_factory=dict)   # the numbers behind the message


class FixMethod(str, Enum):
    SAME_DAYS = "same_days"                  # first N days of both periods
    PER_DAY_AVERAGE = "per_day_average"      # value per complete day
    ALIGN_POPULATION = "align_population"    # same filters on both sides
    CONVERT_UNIT = "convert_unit"


class ProposedFix(Contract):
    method: FixMethod
    description: str                   # e.g. "Compare 1-23 August with 1-23 July"
    justification: str                 # WHY, with numbers, e.g. "from 24 August volume < 60% of usual"
    period: Period
    compare_to: Period
    unit: str | None = None            # e.g. "BRL" or "BRL/day" for a per-day average
    value_current: float | None = None   # recomputed with the fix
    value_previous: float | None = None
    change_pct: float | None = None


class UserDecision(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ComparisonReport(Artifact):
    has_comparison: bool               # False -> nothing checked, agent status SKIPPED
    checks: list[ComparisonCheck] = Field(default_factory=list)
    proposed_fix: ProposedFix | None = None          # the recommended adjustment
    alternatives: list[ProposedFix] = Field(default_factory=list)   # other valid adjustments
    user_decision: UserDecision = UserDecision.PENDING
    chosen_fix: FixMethod | None = None              # filled by the app when Sarra accepts
