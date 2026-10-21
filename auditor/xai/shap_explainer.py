"""SHAP explainer: per-feature contributions to the Isolation Forest score.

Purely numeric (turning numbers into sentences is the narrator's job).
Adapted from the prototype: the model, the features and the rows now come from
the profiling outputs, described by contracts.quality.AnomalyReport.

Sign convention (same as the prototype):
  sklearn's raw output = average isolation path length (lower = more anomalous).
  We flip the sign so that a POSITIVE shap value pushes TOWARD anomaly.
  base_value and model_output are therefore NEGATIVE path lengths:
  "typical row isolated in 11.6 splits" <-> base_value = -11.6.
"""
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline

from contracts.common import load
from contracts.quality import AnomalyReport


def split_model(model):
    """The profiler may hand over a bare IsolationForest or an sklearn Pipeline
    (e.g. imputer -> IsolationForest). SHAP's TreeExplainer only reads the trees, so a
    Pipeline is split into its preprocessing and its final estimator."""
    if isinstance(model, Pipeline):
        prep = Pipeline(model.steps[:-1]) if len(model.steps) > 1 else None
        return prep, model.steps[-1][1]
    return None, model


def model_matrix(model, X: pd.DataFrame) -> pd.DataFrame:
    """What the trees actually see: X after the pipeline's preprocessing (same columns, same index)."""
    prep, _ = split_model(model)
    if prep is None:
        return X
    return pd.DataFrame(np.asarray(prep.transform(X), dtype=float), index=X.index, columns=X.columns)


@dataclass
class ProfilingOutputs:
    """Everything profiling handed over, loaded and checked."""
    report: AnomalyReport
    model: IsolationForest | Pipeline
    scores: pd.DataFrame       # row_key + features + anomaly_score + is_anomaly

    @property
    def X(self) -> pd.DataFrame:
        """Feature matrix as the profiler stored it, indexed by the row key (e.g. payment_id)."""
        return self.scores.set_index(self.report.row_key)[self.report.features]

    @property
    def X_model(self) -> pd.DataFrame:
        """The same rows after the model's preprocessing (identical to X for a bare forest)."""
        return model_matrix(self.model, self.X)

    @property
    def estimator(self) -> IsolationForest:
        return split_model(self.model)[1]


def load_profiling(anomalies: Path, model: Path, scores: Path) -> ProfilingOutputs:
    report = load(AnomalyReport, anomalies)
    df = pd.read_parquet(scores)
    expected = [report.row_key, *report.features, "anomaly_score", "is_anomaly"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"{scores} is missing columns required by the contract: {missing}")
    return ProfilingOutputs(report=report, model=joblib.load(model), scores=df)


@dataclass
class RowExplanation:
    """Numeric evidence for ONE row."""
    row_key: str
    values: pd.Series          # feature -> value
    shap: pd.Series            # feature -> contribution (> 0 = toward anomaly)
    base_value: float          # typical row (negative path length)
    model_output: float        # this row (= base_value + shap.sum())

    @property
    def typical_splits(self) -> float:
        return -self.base_value

    @property
    def splits(self) -> float:
        return -self.model_output

    def sorted_contributions(self) -> pd.DataFrame:
        df = pd.DataFrame({"feature": self.shap.index, "value": self.values.values,
                           "shap_value": self.shap.values})
        return df.reindex(df["shap_value"].abs().sort_values(ascending=False).index
                          ).reset_index(drop=True)


def build_explainer(model) -> shap.TreeExplainer:
    """Create the explainer ONCE and reuse it for every row. Accepts a forest or a Pipeline:
    feed it model_matrix(model, X), not the raw X."""
    return shap.TreeExplainer(split_model(model)[1])


def explain_rows(explainer: shap.TreeExplainer, X: pd.DataFrame) -> list[RowExplanation]:
    """Explain many rows in one SHAP call (much faster than row by row)."""
    raw = np.atleast_2d(explainer.shap_values(X))
    base_value = -float(np.ravel(explainer.expected_value)[0])
    out = []
    for i, key in enumerate(X.index):
        contrib = pd.Series(-raw[i], index=X.columns)
        out.append(RowExplanation(row_key=str(key), values=X.iloc[i], shap=contrib,
                                  base_value=base_value,
                                  model_output=base_value + float(contrib.sum())))
    return out


def path_length_to_score(model_output: float, max_samples: int) -> float:
    """Rebuild the profiler's anomaly_score from SHAP's output.

    Isolation Forest: score = 2 ** (-avg_path / c(n)), c(n) = average path length
    of an unsuccessful search in a binary tree of n samples.
    If this equals anomaly_score, SHAP explains EXACTLY the score that took the decision.
    """
    n = max_samples
    c = 2.0 * (np.log(n - 1) + np.euler_gamma) - 2.0 * (n - 1) / n
    return float(2 ** (model_output / c))     # model_output = -avg_path
