"""Generalization: the SAME code on a dataset unlike Olist (clinics in Tunisia, fees in TND).
python -m pytest tests/test_generalization.py -v

Nothing is configured for this dataset: every agent finds its way through the contract files
(coverage profile, catalog, manifest, receipts, lineage, anomaly report).
"""
from pathlib import Path

import pandas as pd
import pytest

from auditor.agent import run as run_auditor
from auditor.drift.monitor import monitor_runs
from auditor.tools import Toolbox
from auditor.why import WhyAgent
from auditor.xai.explain import build_report
from comparisons.checker import run as run_checker
from contracts.agent import AgentStatus, RunContext
from contracts.audit import read_events, verify_journal
from contracts.comparisons import CheckKind, CheckStatus, ComparisonReport, FixMethod
from contracts.common import load
from contracts.llm import LLMUnavailable, ToolCall
from contracts.pipeline import output_path
from sklearn.ensemble import IsolationForest

from auditor.dev import clinics

RUN = "clinic_001"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("clinics")
    df = clinics.visits()
    clinics.write_run(root, RUN, df)
    runs, journal = root / "runs", root / "journal.db"
    inputs = {k: output_path(RUN, *ref.split("."), runs) for k, ref in {
        "request": "request.request", "result": "analysis.result", "coverage": "profiling.coverage",
        "warehouse": "etl.warehouse", "manifest": "etl.manifest", "receipts": "etl.receipts"}.items()}
    inputs["catalog"] = root / "kpi" / "catalog.yaml"
    res = run_checker(RunContext(run_id=RUN, agent="comparisons", inputs=inputs,
                                 output_dir=runs / RUN / "comparisons", params={"llm": False}, journal=journal))
    return root, runs, journal, df, res


def checks(report):
    return {c.kind: c for c in report.checks}


# ---- BO4-12 -------------------------------------------------------------------------
def test_bo4_12_finds_the_clinic_traps(world):
    root, runs, _, _, res = world
    rep = load(ComparisonReport, res.outputs["report"])
    c = checks(rep)
    assert res.status == AgentStatus.NEEDS_REVIEW
    assert c[CheckKind.COVERAGE].status == CheckStatus.BLOCKING
    assert c[CheckKind.COVERAGE].evidence["last_complete_day"] == "2024-03-13"     # extraction lag
    assert c[CheckKind.SCALE].status == CheckStatus.WARNING                           # 31 vs 29 days
    assert c[CheckKind.POPULATION].evidence["region_only_current"] == ["Gabes"]       # new clinic
    assert c[CheckKind.UNIT].status == CheckStatus.OK and "TND" in c[CheckKind.UNIT].message
    assert c[CheckKind.GRAIN].status == CheckStatus.OK


def test_the_right_coverage_table_is_used_not_the_first(world):
    rep = load(ComparisonReport, world[4].outputs["report"])
    assert checks(rep)[CheckKind.COVERAGE].evidence["table"] == "visits"     # 'appointments' is first
    assert "visits per day" in checks(rep)[CheckKind.COVERAGE].message


def test_quiet_sundays_are_not_missing_data(world):
    rep = load(ComparisonReport, world[4].outputs["report"])
    prev = checks(rep)[CheckKind.COVERAGE].evidence["previous"]
    assert prev["complete"] == {"start": "2024-02-01", "end": "2024-02-29"}


def test_the_fix_is_recomputed_on_the_clinic_warehouse(world):
    _, _, _, df, res = world
    fix = load(ComparisonReport, res.outputs["report"]).proposed_fix
    assert fix.method == FixMethod.SAME_DAYS and fix.unit == "TND"
    assert (fix.period.end, fix.compare_to.end) == ("2024-03-13", "2024-02-13")
    done = df[df["visit_state"] == "completed"]
    expect = done[(done["visit_date"] >= pd.Timestamp("2024-03-01").date())
                  & (done["visit_date"] <= pd.Timestamp("2024-03-13").date())]["fee_tnd"].sum()
    assert fix.value_current == pytest.approx(round(expect, 2), abs=0.01)


# ---- SHAP -----------------------------------------------------------------------------
def test_shap_speaks_the_clinic_language(world):
    root, runs, *_ = world
    rep = build_report(*(output_path(RUN, "profiling", k, runs) for k in ("anomalies", "model", "scores")))
    text = " ".join(e.narrative for e in rep.explanations if e.is_anomaly)
    assert "Consultation fee" in text or "Number of procedures" in text
    assert "BRL" not in text and "Payment" not in text


def test_without_labels_the_column_names_stay_readable(tmp_path):
    df = clinics.visits()
    clinics.write_run(tmp_path, "nolabels", df, labels=False)
    rep = build_report(*(output_path("nolabels", "profiling", k, tmp_path / "runs")
                         for k in ("anomalies", "model", "scores")))
    text = " ".join(e.narrative for e in rep.explanations if e.is_anomaly)
    assert "Fee tnd" in text or "N procedures" in text


# ---- journal, auditor agent, why? ---------------------------------------------------------
def test_auditor_agent_runs_on_clinics(world):
    root, runs, journal, *_ = world
    ctx = RunContext(run_id=RUN, agent="auditor",
                     inputs={k: output_path(RUN, "profiling", k, runs) for k in ("anomalies", "model", "scores")},
                     output_dir=runs / RUN / "auditor", journal=journal, params={"n_normal": 5})
    assert run_auditor(ctx).status == AgentStatus.SUCCESS
    assert verify_journal(journal).ok


def test_why_tools_work_on_clinics(world):
    root, runs, journal, *_ = world
    t = Toolbox(RUN, journal, runs_root=runs, repo_root=root)
    assert "visits.csv / fee_tnd" in t.call("trace_lineage", {"node": "kpi:Consultation revenue@1.0"})
    assert '"unit": "TND"' in t.call("kpi_definition", {"name": "Consultation revenue"})
    assert "Gabes" in t.call("read_report", {"name": "comparison"})


def test_why_agent_answers_about_clinics(world):
    root, runs, journal, *_ = world
    cov = next(e.entry_id for e in read_events(journal, run_id=RUN) if e.step == "check_coverage")
    moves = iter([ToolCall(name="search_journal", args={"step": "check_coverage"}, id="a"),
                  ToolCall(name="final_answer", id="b", args={
                      "answer": f"Bloqué (#{cov}) : mars n'est complet que jusqu'au 2024-03-13.",
                      "citations": [cov]})])
    agent = WhyAgent(RUN, journal=journal, runs_root=runs, repo_root=root,
                     llm=lambda messages, tools, **kw: (next(moves), {"role": "assistant", "content": ""}),
                     writer=lambda *a, **k: (_ for _ in ()).throw(LLMUnavailable("none")))
    a = agent.ask("Pourquoi la comparaison mars/février a-t-elle été bloquée ?")
    assert a.source.startswith("llm:") and a.citations == [cov]


# ---- drift ------------------------------------------------------------------------------
def test_drift_on_clinic_months(tmp_path):
    df = clinics.visits()
    df["month"] = pd.to_datetime(df["visit_date"]).dt.strftime("%Y-%m")
    ref_months = ["2023-10", "2023-11", "2023-12", "2024-01"]
    train = df[df["month"].isin(ref_months)]
    model = IsolationForest(n_estimators=100, contamination=0.01, random_state=0).fit(train[clinics.FEATURES])
    for m in ref_months + ["2024-02"]:
        clinics.write_run(tmp_path, f"m_{m}", df[df["month"] == m].reset_index(drop=True), model=model)
    drifted = df[df["month"] == "2024-02"].reset_index(drop=True).copy()
    drifted["fee_tnd"] *= 1.6                                       # fees rise by 60%
    clinics.write_run(tmp_path, "m_2024-02_fees_up", drifted, model=model)

    reports = monitor_runs([f"m_{m}" for m in ref_months], ["m_2024-02", "m_2024-02_fees_up"],
                           runs_root=tmp_path / "runs", journal=tmp_path / "j.db")
    assert reports["m_2024-02"].status == "stable"
    assert reports["m_2024-02_fees_up"].status == "data_drift"
    assert any(c.name == "fee_tnd" and c.flagged for c in reports["m_2024-02_fees_up"].input_checks)


# ---- the run's own catalog (2nd dataset in the same repo, Olist catalog untouched) --------
def test_a_run_can_carry_its_own_catalog(tmp_path):
    from contracts.pipeline import resolve
    repo, runs = tmp_path / "repo", tmp_path / "runs"
    (repo / "kpi").mkdir(parents=True)
    (repo / "kpi" / "catalog.yaml").write_text("olist", encoding="utf-8")
    clinics.write_run(tmp_path, "clinic_x", clinics.visits(), own_catalog=True)
    assert resolve("static:kpi/catalog.yaml", "clinic_x", runs, repo) == runs / "clinic_x/static/kpi/catalog.yaml"
    assert resolve("static:kpi/catalog.yaml", "run_001", runs, repo) == repo / "kpi/catalog.yaml"
    assert (repo / "kpi" / "catalog.yaml").read_text(encoding="utf-8") == "olist"
    assert '"unit": "TND"' in Toolbox("clinic_x", tmp_path / "j.db", runs_root=runs, repo_root=repo).call(
        "kpi_definition", {"name": "Consultation revenue"})
