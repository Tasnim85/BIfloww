"""Tests of step 5 (drift) on real Olist months with planted events.
python -m pytest tests/test_drift.py -v      (needs data/olist/*.csv)

The monitor never reads the planted truth: it is compared only here, after the fact.
"""
from pathlib import Path

import numpy as np
import pytest

from auditor.agent import run as run_auditor
from auditor.dev.simulate_runs import MONITORED, REFERENCE, simulate
from auditor.drift import stats
from auditor.drift.monitor import monitor_runs
from auditor.tools import Toolbox
from contracts.agent import AgentStatus, RunContext
from contracts.audit import read_events, verify_journal

DATA = Path("data/olist")
pytestmark = pytest.mark.skipif(not (DATA / "olist_orders_dataset.csv").exists(),
                                reason="needs the Olist CSVs in data/olist")


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    truth = simulate(DATA, root)
    journal = root / "drift.db"
    reports = monitor_runs(REFERENCE, MONITORED, runs_root=root, journal=journal)
    return root, truth, reports, journal


# ---- statistics ---------------------------------------------------------------------
def test_stats_sanity():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 3000)
    assert stats.psi(ref, rng.normal(0, 1, 1000)) < 0.10
    assert stats.psi(ref, rng.normal(1, 1, 1000)) > 0.25
    assert stats.control_limits([8, 8, 8], min_rel_sigma=0.05) == (8.0, 6.8, 9.2)


# ---- the scenario -------------------------------------------------------------------
EXPECTED = {
    "run_2018_04": ("stable", []),
    "run_2018_05": ("agent_changed", ["profiling"]),      # contamination 0.01 -> 0.03
    "run_2018_06": ("agent_changed", ["etl"]),            # ETL loses 8% of rows
    "run_2018_07": ("data_drift", ["profiling"]),         # payment values x1.5
    "run_2018_08": ("stable", []),
}


@pytest.mark.parametrize("run", MONITORED)
def test_each_month_gets_the_right_diagnosis(sim, run):
    _, truth, reports, _ = sim
    assert (reports[run].status, reports[run].flagged_agents) == EXPECTED[run], truth[run]


def test_no_false_alarm_on_real_untouched_months(sim):
    _, _, reports, _ = sim
    for run in ("run_2018_04", "run_2018_08"):
        assert not any(c.out_of_control for c in reports[run].metric_checks)
        assert not any(c.flagged for c in reports[run].input_checks)


def test_explanations_tell_a_setting_change_from_a_data_change(sim):
    """May: decisions moved but the model's reasoning did not -> a setting changed.
    July: the reasoning moved with the data -> the data changed."""
    _, _, reports, _ = sim
    shap_out = lambda r: [c.name for c in r.metric_checks if c.out_of_control and c.name.startswith("shap_share_")]  # noqa: E731
    assert shap_out(reports["run_2018_05"]) == []
    assert "SETTING changed" in reports["run_2018_05"].narrative
    assert "shap_share_payment_value" in shap_out(reports["run_2018_07"])


def test_alerts_are_journaled_under_each_run(sim):
    _, _, _, journal = sim
    july = read_events(journal, run_id="run_2018_07")
    assert {e.step for e in july} >= {"D1_data_drift", "D2_decision_drift", "D3_diagnosis"}
    assert [e.decision for e in read_events(journal, run_id="run_2018_04")] == ["stable"]
    assert verify_journal(journal).ok


def test_why_agent_can_read_the_drift_report(sim):
    root, _, _, journal = sim
    out = Toolbox("run_2018_06", journal, runs_root=root).call("read_report", {"name": "drift"})
    assert "status: agent_changed" in out and "load_ratio" in out and "Journal entries behind" in out


def test_auditor_agent_computes_drift_from_reference_runs(sim, tmp_path):
    root, _, _, _ = sim
    ctx = RunContext(run_id="run_2018_07", agent="auditor",
                     inputs={k: root / "run_2018_07" / "profiling" / f for k, f in
                             {"anomalies": "anomaly_report.json", "model": "anomaly_model.joblib",
                              "scores": "anomaly_scores.parquet"}.items()},
                     output_dir=root / "run_2018_07" / "auditor", journal=tmp_path / "j.db",
                     params={"drift_reference": REFERENCE, "n_normal": 5})
    res = run_auditor(ctx)
    assert res.status == AgentStatus.NEEDS_REVIEW and "drift: data_drift" in res.message
