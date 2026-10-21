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


def test_pii_review_can_be_settled_by_a_human(tmp_path, monkeypatch):
    """llama3 unsure about customer_state -> the run pauses; the reviewer's answer lets it continue."""
    import privacy.agent as pii
    from contracts import AgentStatus, RunContext, read_events
    from privacy.detection import ColumnPrediction

    tables = tmp_path / "tables"; tables.mkdir()
    pd.DataFrame({"customer_id": ["a1", "b2", "c3"], "customer_state": ["SP", "RJ", "SP"]}).to_csv(tables / "customers.csv", index=False)
    monkeypatch.setenv("BO2_PII_SECRET", "x" * 40)
    monkeypatch.setattr(pii.detection, "classify_columns", lambda frames, **kw: {"customers": {
        "customer_id": ColumnPrediction(semantic_type="INTERNAL_KEY", confidence=0.95),
        "customer_state": ColumnPrediction(semantic_type="CATEGORY", confidence=0.6)}})

    def run(out, **params):
        return pii.run(RunContext(run_id="t", agent="pii", inputs={"tables": tables}, output_dir=tmp_path / out,
                                  params=params, journal=tmp_path / "journal.db"))

    assert run("first").status == AgentStatus.NEEDS_REVIEW
    settled = run("second", pii_overrides={"customers.customer_state": "CATEGORY"})
    assert settled.status == AgentStatus.SUCCESS
    masked = pd.read_parquet(tmp_path / "second" / "tables" / "customers.parquet")
    assert sorted(masked["customer_state"]) == ["RJ", "SP", "SP"]          # kept for the "by state" analyses
    assert any(e.evidence.get("classification_source") == "human_review" for e in read_events(tmp_path / "journal.db"))


def test_steps_after_a_needs_review_wait_instead_of_crashing(tmp_path):
    """PII stops for a human: profiling and everything after it must wait (not run on missing files)."""
    from unittest import mock
    import orchestrator.dag_runner as runner
    from contracts import AgentResult, AgentStatus

    def fake_import(entrypoint):
        def agent(ctx):
            status = AgentStatus.NEEDS_REVIEW if ctx.agent == "pii" else AgentStatus.SUCCESS
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            for k, f in runner.STEPS[ctx.agent].outputs.items():
                p = ctx.output_dir / f
                if f.endswith("/"):
                    p.mkdir(parents=True, exist_ok=True)
                elif f.endswith(".parquet"):
                    p.write_bytes(b"PAR1testparquetdataPAR1")
                else:
                    p.write_text("{}", encoding="utf-8")
            return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=status, message="")
        return agent

    with mock.patch.object(runner, "_import_run", side_effect=fake_import):
        res = runner.run_pipeline(run_id="r", runs_root=tmp_path / "runs", journal=tmp_path / "j.db",
                                  db=tmp_path / "t.db", params={})
    assert res["pii"].status == AgentStatus.NEEDS_REVIEW
    for step in ("profiling", "cleaning", "etl", "analysis", "comparisons", "dashboard", "auditor"):
        assert res[step].status == AgentStatus.SKIPPED and "human review" in res[step].message
    assert res["request"].status == AgentStatus.SUCCESS          # independent of PII: still runs
