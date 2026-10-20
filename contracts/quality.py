"""Step 2: profiling + anomalies (Ahmed) and cleaning (Ikbel).

ProfileReport   Ahmed -> Ikbel (what to clean), app
AnomalyReport   Ahmed -> Tasnim (Auditor explains the anomalies with SHAP)
CleaningRule    the shape of ONE rule, in a playbook or proposed by the LLM (2b)
Playbook        a versioned set of rules, YAML in cleaning/playbooks/<name>@<version>.yaml
CleaningReport  Ikbel -> Ahmed (ETL), Auditor
"""
from datetime import datetime
from enum import Enum

from pydantic import Field

from contracts.common import Artifact, Contract, SemanticType


# ---- Profiling ------------------------------------------------------------------
class ColumnProfile(Contract):
    name: str
    dtype: str                        # pandas dtype, e.g. "float64", "object"
    semantic_type: SemanticType | None = None
    missing: int
    missing_pct: float                # [0, 1]
    distinct: int
    min: float | str | None = None
    max: float | str | None = None


class TableProfile(Contract):
    table: str
    rows: int
    duplicate_rows: int
    columns: list[ColumnProfile]


class ProfileReport(Artifact):
    tables: list[TableProfile]


# ---- Anomalies -------------------------------------------------------------------
class AnomalyReport(Artifact):
    """The anomaly DECISIONS. The Auditor explains them; it never changes them.

    anomaly_scores.parquet has one row per audited row with columns:
        <row_key>, every feature in `features`, anomaly_score, is_anomaly
    (higher anomaly_score = more anomalous). The features are inside the file so
    the Auditor can run SHAP without re-reading the tables.
    """
    table: str                        # e.g. "order_payments"
    row_key: str                      # column that identifies a row, e.g. "order_id"
    model: str                        # e.g. "IsolationForest"
    model_version: str                # e.g. "iforest@1.0"
    params: dict                      # e.g. {"n_estimators": 100, "contamination": 0.03, ...}
    features: list[str]
    model_file: str = "anomaly_model.joblib"     # joblib.dump of the fitted sklearn model
    scores_file: str = "anomaly_scores.parquet"
    n_rows: int
    n_anomalies: int


# ---- Cleaning --------------------------------------------------------------------
class CleaningAction(str, Enum):
    FILL_MEDIAN = "fill_median"
    FILL_VALUE = "fill_value"           # params: {"value": ...}
    DROP_ROW = "drop_row"               # params: {"when": "<pandas query>"}
    DROP_DUPLICATES = "drop_duplicates"  # params: {"subset": [...]} (optional)
    TO_ABS = "to_abs"
    NORMALIZE_TEXT = "normalize_text"    # strip + lower/title, params: {"case": "title"}
    CAST = "cast"                        # params: {"dtype": "datetime64[ns]"}
    CLIP = "clip"                        # params: {"lower": ..., "upper": ...}


class CleaningRule(Contract):
    rule_id: str                        # e.g. "R1_fill_median_weight"
    table: str
    column: str | None = None           # None = whole row
    action: CleaningAction
    params: dict = Field(default_factory=dict)
    description: str                    # one sentence, shown by the Auditor as the "why"


class Playbook(Contract):
    name: str                           # e.g. "olist"
    version: str                        # e.g. "1.3"  (new LLM rules approved -> 1.4)
    source: str                         # "manual" | "llm"
    approved_by: str | None = None      # None = not approved yet: must not run
    approved_at: datetime | None = None
    rules: list[CleaningRule]

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"   # used as rule_version "playbook:olist@1.3"


class RuleApplication(Contract):
    rule_id: str
    table: str
    column: str | None = None
    rows_affected: int


class CleaningReport(Artifact):
    """If no playbook matched: playbook=None, proposed_rules filled, agent status NEEDS_REVIEW."""
    playbook: str | None                # "olist@1.3"
    applied: list[RuleApplication] = Field(default_factory=list)
    proposed_rules: list[CleaningRule] = Field(default_factory=list)   # from the LLM (2b)
    rows_before: dict[str, int]         # table -> rows
    rows_after: dict[str, int]
    tables: dict[str, str]              # table -> parquet file name inside cleaning/tables/
