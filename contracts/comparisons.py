"""Step 6 checks: misleading-comparison detection (BO4-12). Owner: Tasnim.
Read by: dashboard (Samar) to show the warning, Auditor.

If a check is BLOCKING and a fix is proposed, the agent returns NEEDS_REVIEW:
the app asks Sarra to accept or refuse the fix, and writes her decision back.
"""
from enum import Enum

from pydantic import Field

from contracts.common import Artifact, Contract, Period


class CheckKind(str, Enum):
    COVERAGE = "coverage"        # one period has fewer days of data (partial month)
    UNIT = "unit"                # the two values are not in the same unit
    GRAIN = "grain"              # one row = order vs one row = order item
    POPULATION = "population"    # not the same filters / scope / customers


class CheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"          # show it, the comparison stays
    BLOCKING = "blocking"        # do not show the comparison as is


class ComparisonCheck(Contract):
    kind: CheckKind
    status: CheckStatus
    message: str                       # plain sentence for Sarra
    evidence: dict = Field(default_factory=dict)


class ProposedFix(Contract):
    description: str                   # e.g. "Compare 1-29 August with 1-29 July"
    period: Period
    compare_to: Period
    value_current: float | None = None   # recomputed with the fix, if available
    value_previous: float | None = None
    change_pct: float | None = None


class UserDecision(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ComparisonReport(Artifact):
    has_comparison: bool               # False -> nothing checked, agent status SKIPPED
    checks: list[ComparisonCheck] = Field(default_factory=list)
    proposed_fix: ProposedFix | None = None
    user_decision: UserDecision = UserDecision.PENDING
