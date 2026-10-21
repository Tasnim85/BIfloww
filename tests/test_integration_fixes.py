"""Regressions found while integrating feature/rabeb (all agents) with feature/tasnim."""
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from auditor.xai.explain import build_report
from contracts.common import save
from contracts.quality import AnomalyReport
from etl.analytics import agreed_view


def test_auditor_explains_a_profiler_pipeline_with_integer_row_keys(tmp_path):
    """Ahmed's profiler hands over imputer -> IsolationForest and an integer row key (source_row)."""
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"amount": rng.normal(100, 10, 400), "installments": rng.integers(1, 5, 400).astype(float)})
    X.loc[3, "amount"] = 900.0
    X.loc[7, "installments"] = np.nan                       # the imputer must handle it
    model = Pipeline([("imputer", SimpleImputer(strategy="median")),
                      ("isolation_forest", IsolationForest(contamination=0.01, random_state=42))]).fit(X)
    scores = X.copy()
    scores.insert(0, "source_row", range(len(X)))           # integer key
    scores["anomaly_score"] = -model.score_samples(X)
    scores["is_anomaly"] = model.predict(X) == -1
    scores.to_parquet(tmp_path / "scores.parquet")
    joblib.dump(model, tmp_path / "model.joblib")
    save(AnomalyReport(table="payments", row_key="source_row", model="IsolationForest", model_version="iforest@2.0",
                       params={}, features=["amount", "installments"], n_rows=len(X),
                       n_anomalies=int(scores["is_anomaly"].sum())), tmp_path / "anomalies.json")

    report = build_report(tmp_path / "anomalies.json", tmp_path / "model.joblib", tmp_path / "scores.parquet", n_normal=5)

    flagged = [e for e in report.explanations if e.is_anomaly]
    assert flagged and any(e.row_key == "3" for e in flagged)
    top = next(e for e in report.explanations if e.row_key == "3").contributions[0]
    assert top.feature == "amount"                          # the planted cause is named first
    assert all(np.isfinite(c.value) for e in report.explanations for c in e.contributions)


def test_view_names_match_the_files_renamed_by_the_pii_step():
    agreed = {"olist_order_payments_dataset": {"name": "fact_payments"}, "olist_customers_dataset": {"name": "dim_customer"}}
    assert agreed_view(agreed, "olist_order_payments_dataset")["name"] == "fact_payments"
    assert agreed_view(agreed, "order_payments")["name"] == "fact_payments"   # what PII publishes
    assert agreed_view(agreed, "customers")["name"] == "dim_customer"
    assert agreed_view(agreed, "reviews") == {}
