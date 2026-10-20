"""Step 5: the Analyst. Owner: Rabeb. Read by: comparisons (Tasnim), dashboard (Samar), Auditor.

result.parquet columns:  <one column per requested dimension>, period, value
    period = "current" | "previous"   ("previous" rows only if the request has compare_to)
"""
from pydantic import Field

from contracts.common import Artifact, Contract
from contracts.semantic import AnalysisRequest


class ValidationCheck(Contract):
    """One BO3-03 check run on the answer, e.g. join multiplicity, grain match."""
    name: str                          # e.g. "join_multiplicity", "grain_matches_kpi"
    passed: bool
    detail: str                        # one sentence with the numbers


class Insight(Contract):
    text: str                          # e.g. "SP makes 45% of revenue"
    evidence: dict = Field(default_factory=dict)   # the numbers behind the sentence


class AnalysisResult(Artifact):
    request: AnalysisRequest           # copy of the request answered
    kpi: str                           # "Revenue@2.0": catalog name + version used
    sql: str                           # exact query run on the warehouse
    data_file: str = "result.parquet"
    rows: int                          # rows in result.parquet
    value_current: float               # total over the whole period
    value_previous: float | None = None
    change_pct: float | None = None    # (current - previous) / previous
    unit: str
    validations: list[ValidationCheck]
    insights: list[Insight] = Field(default_factory=list)
