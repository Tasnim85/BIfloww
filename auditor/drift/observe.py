"""Turns one pipeline run into an Observation: what went IN (input distributions)
and what came OUT (decision metrics), read only from the run's files via the contracts.

Observed today (agents whose outputs exist):
  profiling   inputs: every model feature (PSI / KS)
              outputs: anomaly_rate, mean_score,
                       shap_share_<feature> = share of each feature in the model's
                       reasoning (mean |SHAP| over a fixed sample of the run's rows)
  etl         output: load_ratio = rows_after / rows_before of the fact table
Add an agent by adding a function to OBSERVERS; the monitor does not change.
"""
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from auditor.xai.shap_explainer import build_explainer, model_matrix
from contracts.common import load
from contracts.pipeline import RUNS_ROOT, output_path
from contracts.quality import AnomalyReport
from contracts.warehouse import TransformationReceipts

SHAP_SAMPLE = 1500          # rows explained per run for the reasoning metrics (fixed seed)


@dataclass(frozen=True)
class Metric:
    value: float
    min_rel_sigma: float = 0.0       # sigma floor used for its control limits


@dataclass
class Observation:
    run_id: str
    inputs: dict = field(default_factory=dict)    # (agent, name) -> np.ndarray
    metrics: dict = field(default_factory=dict)   # (agent, name) -> Metric


def observe_profiling(run_id: str, runs_root: Path, obs: Observation) -> None:
    report = load(AnomalyReport, output_path(run_id, "profiling", "anomalies", runs_root))
    scores = pd.read_parquet(output_path(run_id, "profiling", "scores", runs_root))
    for f in report.features:
        obs.inputs[("profiling", f)] = scores[f].to_numpy(float)
    obs.metrics[("profiling", "anomaly_rate")] = Metric(float(scores["is_anomaly"].mean()))
    obs.metrics[("profiling", "mean_score")] = Metric(float(scores["anomaly_score"].mean()), 0.01)

    model = joblib.load(output_path(run_id, "profiling", "model", runs_root))
    sample = scores[report.features].sample(min(SHAP_SAMPLE, len(scores)), random_state=0)
    importance = np.abs(np.atleast_2d(build_explainer(model).shap_values(model_matrix(model, sample)))).mean(axis=0)
    for f, share in zip(report.features, importance / importance.sum()):
        obs.metrics[("profiling", f"shap_share_{f}")] = Metric(float(share), 0.02)


def observe_etl(run_id: str, runs_root: Path, obs: Observation) -> None:
    receipts = load(TransformationReceipts, output_path(run_id, "etl", "receipts", runs_root))
    for r in receipts.receipts:
        if r.rows_before:
            obs.metrics[("etl", f"load_ratio_{r.output_table}")] = Metric(r.rows_after / r.rows_before, 0.01)


OBSERVERS = [observe_profiling, observe_etl]


def observe_run(run_id: str, runs_root: Path = RUNS_ROOT) -> Observation:
    obs = Observation(run_id)
    for fn in OBSERVERS:
        try:
            fn(run_id, runs_root, obs)
        except FileNotFoundError:
            pass                      # that agent produced nothing in this run: not observed
    return obs
