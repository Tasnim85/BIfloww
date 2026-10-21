"""Tests of step 2 (SHAP on Olist).   python -m pytest tests/test_xai.py -v

Needs the fake inputs of step 1:  python -m auditor.dev.make_fake_inputs
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import IsolationForest

from auditor.xai.explain import build_report
from auditor.xai.narrator import narrate
from auditor.xai.shap_explainer import build_explainer, explain_rows
from contracts.pipeline import context_for
from contracts.xai import ExplanationReport

CTX = context_for("auditor", "run_001")
PATHS = (CTX.inputs["anomalies"], CTX.inputs["model"], CTX.inputs["scores"])
FEATURES = ["payment_value", "payment_installments", "payment_sequential"]

pytestmark = pytest.mark.skipif(
    not all(Path(p).exists() for p in PATHS),
    reason="run `python -m auditor.dev.make_fake_inputs` first")


@pytest.fixture(scope="module")
def report() -> ExplanationReport:
    return build_report(*PATHS, n_normal=30)   # raises if SHAP != profiler score


@pytest.fixture(scope="module")
def scores() -> pd.DataFrame:
    return pd.read_parquet(PATHS[2]).set_index("payment_id")


def test_report_follows_the_contract(report):
    ExplanationReport.model_validate_json(report.model_dump_json())


def test_decisions_are_copied_never_changed(report, scores):
    for e in report.explanations:
        assert e.is_anomaly == bool(scores.at[e.row_key, "is_anomaly"])
        assert e.anomaly_score == pytest.approx(scores.at[e.row_key, "anomaly_score"], abs=1e-6)


def test_contributions_add_up(report):
    for e in report.explanations:
        total = e.base_value + sum(c.shap_value for c in e.contributions)
        assert total == pytest.approx(e.model_output, abs=1e-4)


def test_every_anomaly_names_at_least_one_feature(report):
    for e in report.explanations:
        if e.is_anomaly:
            assert e.narrative.startswith("Flagged as anomalous because")


def test_ordinary_rows_are_not_overexplained(report):
    ordinary = [e for e in report.explanations
                if not e.is_anomaly and -e.model_output >= -e.base_value - 1.0]
    assert ordinary, "expected at least one ordinary normal row in the sample"
    for e in ordinary:
        assert "ordinary observation" in e.narrative


def test_planted_anomalies_are_blamed_on_the_planted_feature(scores):
    """Ground truth we control: tamper with ONE feature, SHAP must point at it."""
    rng = np.random.default_rng(0)
    base = scores[~scores["is_anomaly"]][FEATURES].sample(3000, random_state=0)
    typical = base.median()
    planted = pd.DataFrame([typical] * 3, index=["A_value", "B_installments", "C_sequential"])
    planted.loc["A_value", "payment_value"] = 9000.0          # huge amount, nothing else odd
    planted.loc["B_installments", "payment_installments"] = 24  # max installments, normal amount
    planted.loc["C_sequential", "payment_sequential"] = 25      # 25th payment of one order
    data = pd.concat([base, planted])

    model = IsolationForest(n_estimators=200, random_state=int(rng.integers(1000))).fit(data)
    explanations = explain_rows(build_explainer(model), planted)
    expected = {"A_value": "payment_value", "B_installments": "payment_installments",
                "C_sequential": "payment_sequential"}
    for exp in explanations:
        top = exp.sorted_contributions().iloc[0]["feature"]
        assert top == expected[exp.row_key], f"{exp.row_key}: SHAP blamed {top}"
        print(exp.row_key, "->", narrate(exp, True, data.median()))
