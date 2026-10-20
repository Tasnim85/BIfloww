"""Step 7: what the Auditor writes. Owner: Tasnim. Read by: the app (Samar).

ExplanationReport  SHAP explanation of the anomaly decisions taken by profiling
DriftReport        is this run still behaving like the reference runs?
(integrity_report.json uses contracts.audit.IntegrityReport)
"""
from pydantic import Field

from contracts.common import Artifact, Contract


class FeatureContribution(Contract):
    feature: str
    value: float
    shap_value: float                  # > 0 pushes TOWARD anomaly


class AnomalyExplanation(Contract):
    row_key: str                       # value of AnomalyReport.row_key for this row
    is_anomaly: bool                   # the decision, copied, never changed
    anomaly_score: float
    base_value: float                  # SHAP expected value (typical row)
    model_output: float                # base_value + sum of shap values
    contributions: list[FeatureContribution]   # sorted by |shap_value|
    narrative: str                     # template sentence, every word traceable to a number


class ExplanationReport(Artifact):
    table: str
    model_version: str                 # copied from AnomalyReport
    explainer: str                     # e.g. "shap.TreeExplainer"
    explanations: list[AnomalyExplanation]


class InputDriftCheck(Contract):
    agent: str
    name: str                          # input variable
    psi: float
    ks_pvalue: float
    flagged: bool                      # PSI > 0.25


class MetricDriftCheck(Contract):
    agent: str
    name: str                          # output metric, e.g. "anomaly_rate", "load_ratio"
    value: float
    center: float
    lower: float
    upper: float
    out_of_control: bool


class DriftReport(Artifact):
    reference_runs: list[str]          # runs that define "normal"
    current_run: str
    status: str                        # reference | stable | data_drift | data_drift_only | agent_changed
    input_checks: list[InputDriftCheck] = Field(default_factory=list)
    metric_checks: list[MetricDriftCheck] = Field(default_factory=list)
    flagged_agents: list[str] = Field(default_factory=list)
    narrative: str                     # "a diagnosis, not a proof: a human decides"
