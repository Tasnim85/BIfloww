"""Tests for dashboard_ai (BO4 step 6): chart choice + misleading-visual detection."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.agent import AgentStatus, RunContext
from contracts.analysis import AnalysisResult
from contracts.common import Period, save
from contracts.comparisons import (CheckKind, CheckStatus, ComparisonCheck, ComparisonReport, FixMethod,
                                   ProposedFix, UserDecision)
from contracts.dashboard import ChartType
from contracts.semantic import AnalysisRequest
from dashboard_ai.agent import build_dashboard, run
from dashboard_ai.models import IssueKind
from dashboard_ai.profile import is_additive

P1 = Period(start="2018-08-01", end="2018-08-31")
P0 = Period(start="2018-07-01", end="2018-07-31")
SUM_SQL = "SELECT SUM(payment_value) AS value FROM fact_payments"


def make(question="Revenue by state", dims=("customer_state",), compare=False, sql=SUM_SQL, cur=1000.0, prev=None):
    req = AnalysisRequest(question=question, metric="Revenue", dimensions=list(dims), period=P1,
                          compare_to=P0 if compare else None)
    res = AnalysisResult(request=req, kpi="Revenue@2.0", sql=sql, rows=1, value_current=cur, value_previous=prev,
                         change_pct=((cur - prev) / prev) if prev else None, unit="BRL", validations=[])
    return req, res


def states(n, base=100.0):
    return pd.DataFrame({"customer_state": [f"S{i:02d}" for i in range(n)],
                         "value": [base * (n - i) for i in range(n)]})


def chosen(spec, cid="c_main"):
    return next(c for c in spec.charts if c.chart_id == cid).chart_type


def kinds(advice):
    return {i.kind for d in advice.decisions for i in d.issues}


# ---------------------------------------------------------------- chart choice
def test_no_dimension_gives_single_kpi_card():
    req, res = make(dims=())
    spec, _, _ = build_dashboard(req, res, None, pd.DataFrame({"value": [1000.0]}))
    assert [c.chart_type for c in spec.charts] == [ChartType.KPI_CARD]


def test_categorical_gives_bar_with_kpi_headline():
    req, res = make()
    spec, advice, _ = build_dashboard(req, res, None, states(5))
    assert chosen(spec) == ChartType.BAR and spec.charts[0].chart_type == ChartType.KPI_CARD
    assert spec.charts[1].y == "value"          # the real column of result.parquet


def test_monthly_series_gives_line():
    req, res = make("Evolution of revenue", dims=("order_month",))
    df = pd.DataFrame({"order_month": ["2018-01", "2018-02", "2018-03", "2018-04"], "value": [1, 2, 3, 4.0]})
    spec, advice, _ = build_dashboard(req, res, None, df)
    assert chosen(spec) == ChartType.LINE and IssueKind.TIME_GAP not in kinds(advice)


def test_two_time_points_do_not_get_a_line():
    req, res = make(dims=("order_month",))
    df = pd.DataFrame({"order_month": ["2018-07", "2018-08"], "value": [1.0, 2.0]})
    spec, _, _ = build_dashboard(req, res, None, df)
    assert chosen(spec) == ChartType.BAR


def test_share_question_with_few_slices_gives_pie():
    req, res = make("Revenue share by payment type", dims=("payment_type",))
    df = pd.DataFrame({"payment_type": ["card", "boleto", "voucher"], "value": [60.0, 30, 10]})
    spec, _, _ = build_dashboard(req, res, None, df)
    assert chosen(spec) == ChartType.PIE


def test_share_question_with_many_slices_falls_back_to_bar():
    req, res = make("Revenue share by state")
    spec, _, _ = build_dashboard(req, res, None, states(27))
    assert chosen(spec) == ChartType.BAR


def test_three_dimensions_give_table():
    req, res = make(dims=("customer_state", "payment_type", "order_month"))
    df = pd.DataFrame({"customer_state": ["SP"], "payment_type": ["card"], "order_month": ["2018-08"], "value": [1.0]})
    spec, _, _ = build_dashboard(req, res, None, df)
    assert chosen(spec) == ChartType.TABLE


# ---------------------------------------------------------------- refused requests
def test_requested_pie_refused_on_27_states_with_reason():
    req, res = make("Revenue by state as a pie chart")
    spec, advice, _ = build_dashboard(req, res, None, states(27))
    assert chosen(spec) == ChartType.BAR
    assert IssueKind.REQUESTED_CHART_REFUSED in kinds(advice)
    assert "27" in spec.warnings[0] or "27" in " ".join(spec.warnings)


def test_requested_pie_refused_when_kpi_not_additive():
    req, res = make("Customers share by payment type camembert", dims=("payment_type",),
                    sql="SELECT COUNT(DISTINCT customer_id) AS value FROM fact_payments")
    df = pd.DataFrame({"payment_type": ["card", "boleto", "voucher"], "value": [60.0, 30, 10]})
    spec, advice, _ = build_dashboard(req, res, None, df)
    assert chosen(spec) != ChartType.PIE and IssueKind.REQUESTED_CHART_REFUSED in kinds(advice)


def test_requested_pie_accepted_when_valid():
    req, res = make("Revenue by payment type as a pie", dims=("payment_type",))
    df = pd.DataFrame({"payment_type": ["card", "boleto"], "value": [60.0, 40]})
    spec, advice, _ = build_dashboard(req, res, None, df)
    assert chosen(spec) == ChartType.PIE and IssueKind.REQUESTED_CHART_REFUSED not in kinds(advice)


def test_requested_line_refused_on_categories():
    req, res = make("Revenue by state as a line chart")
    spec, advice, _ = build_dashboard(req, res, None, states(5))
    assert chosen(spec) == ChartType.BAR and IssueKind.REQUESTED_CHART_REFUSED in kinds(advice)


# ---------------------------------------------------------------- misleading visuals
def test_time_gap_is_flagged_on_line():
    req, res = make(dims=("order_month",))
    df = pd.DataFrame({"order_month": ["2018-01", "2018-02", "2018-05", "2018-06"], "value": [1, 2, 3, 4.0]})
    spec, advice, _ = build_dashboard(req, res, None, df)
    assert chosen(spec) == ChartType.LINE and IssueKind.TIME_GAP in kinds(advice)


def test_dominant_category_flagged():
    req, res = make()
    df = pd.DataFrame({"customer_state": ["SP", "RJ", "MG"], "value": [900.0, 50, 50]})
    _, advice, _ = build_dashboard(req, res, None, df)
    assert IssueKind.DOMINANT_CATEGORY in kinds(advice)


def test_same_level_flagged():
    req, res = make()
    df = pd.DataFrame({"customer_state": ["SP", "RJ", "MG"], "value": [100.0, 99.5, 99.0]})
    _, advice, _ = build_dashboard(req, res, None, df)
    assert IssueKind.SAME_LEVEL in kinds(advice)


def test_base_effect_flagged():
    req, res = make(compare=True, cur=5000.0, prev=50.0, dims=())
    df = pd.DataFrame({"period": ["current", "previous"], "value": [5000.0, 50.0]})
    _, advice, _ = build_dashboard(req, res, None, df)
    assert IssueKind.BASE_EFFECT in kinds(advice)


def test_top_n_groups_others_when_additive():
    req, res = make()
    spec, advice, frames = build_dashboard(req, res, None, states(27))
    main = frames["c_main"]
    assert len(main) == 16 and "Others" in set(main["customer_state"])
    assert main["value"].sum() == pytest.approx(states(27)["value"].sum())   # nothing lost
    assert IssueKind.TOO_MANY_CATEGORIES in kinds(advice)


def test_top_n_does_not_invent_others_for_non_additive():
    req, res = make(sql="SELECT AVG(payment_value) AS value FROM fact_payments")
    _, _, frames = build_dashboard(req, res, None, states(27))
    assert "Others" not in set(frames["c_main"]["customer_state"]) and len(frames["c_main"]) == 15


def test_is_additive():
    assert is_additive("SUM(x)") and is_additive("COUNT(*)")
    assert not is_additive("COUNT(DISTINCT id)") and not is_additive("AVG(x)") and not is_additive("SUM(a)/COUNT(b)")


# ---------------------------------------------------------------- comparison report (BO4-12)
def cmp_df():
    return pd.DataFrame({"customer_state": ["SP", "RJ", "SP", "RJ"], "period": ["current", "current", "previous", "previous"],
                         "value": [60.0, 40, 50, 45]})


def blocked_report(decision=UserDecision.PENDING):
    fix = ProposedFix(method=FixMethod.SAME_DAYS, description="Compare 1-23 August with 1-23 July", justification="x",
                      period=P1, compare_to=P0, value_current=800.0, value_previous=600.0, change_pct=0.3333)
    return ComparisonReport(has_comparison=True, checks=[ComparisonCheck(kind=CheckKind.COVERAGE, status=CheckStatus.BLOCKING,
                            message="August is incomplete from the 24th")], proposed_fix=fix, user_decision=decision)


def test_clean_comparison_gives_grouped_bars():
    req, res = make(compare=True, cur=100.0, prev=95.0)
    report = ComparisonReport(has_comparison=True)
    spec, advice, _ = build_dashboard(req, res, report, cmp_df())
    main = next(c for c in spec.charts if c.chart_id == "c_main")
    assert main.chart_type == ChartType.BAR and main.color == "period" and advice.comparison_shown


def test_blocked_comparison_is_not_drawn_while_pending():
    req, res = make(compare=True, cur=100.0, prev=95.0)
    spec, advice, frames = build_dashboard(req, res, blocked_report(), cmp_df())
    assert not advice.comparison_shown
    assert "period" not in frames["c_main"].columns and len(frames["c_main"]) == 2
    assert any(w.startswith("[BLOCKING]") for w in spec.warnings)
    assert any("Suggested fix" in w for w in spec.warnings)
    assert "vs previous" not in spec.charts[0].title


def test_accepted_fix_uses_adjusted_headline():
    req, res = make(compare=True, cur=100.0, prev=95.0)
    spec, advice, _ = build_dashboard(req, res, blocked_report(UserDecision.ACCEPTED), cmp_df())
    assert "+33.3%" in spec.charts[0].title and IssueKind.COMPARISON_ADJUSTED in kinds(advice)


def test_rejected_fix_draws_comparison_with_warning():
    req, res = make(compare=True, cur=100.0, prev=95.0)
    spec, advice, _ = build_dashboard(req, res, blocked_report(UserDecision.REJECTED), cmp_df())
    assert advice.comparison_shown and any("[BLOCKING]" in w for w in spec.warnings)


def test_comparison_of_months_aligns_by_position():
    req, res = make(compare=True, dims=("order_month",), cur=10.0, prev=9.0)
    df = pd.DataFrame({"order_month": ["2018-06", "2018-07", "2018-08", "2018-07", "2018-08", "2018-09"],
                       "period": ["previous"] * 3 + ["current"] * 3, "value": [1, 2, 3, 4, 5, 6.0]})
    df.loc[df.period == "previous", "order_month"] = ["2018-03", "2018-04", "2018-05"]
    spec, _, frames = build_dashboard(req, res, ComparisonReport(has_comparison=True), df)
    main = next(c for c in spec.charts if c.chart_id == "c_main")
    assert main.chart_type == ChartType.LINE and main.x == "position"
    assert set(frames["c_main"]["position"]) == {1, 2, 3}


# ---------------------------------------------------------------- the agent plug
def test_run_writes_spec_data_and_advice(tmp_path):
    req, res = make("Revenue by state as a pie chart")
    inputs = {"request": save(req, tmp_path / "req.json"), "result": save(res, tmp_path / "res.json"),
              "comparisons": save(ComparisonReport(has_comparison=False), tmp_path / "cmp.json"),
              "data": tmp_path / "result.parquet"}
    states(27).to_parquet(inputs["data"], index=False)
    ctx = RunContext(run_id="run_t", agent="dashboard", inputs=inputs, output_dir=tmp_path / "out",
                     params={"lang": "fr"}, journal=tmp_path / "audit.db")
    out = run(ctx)
    assert out.status == AgentStatus.SUCCESS
    assert Path(out.outputs["spec"]).exists() and (tmp_path / "out" / "chart_advice.json").exists()
    assert (tmp_path / "out" / "c_main.parquet").exists() and (tmp_path / "out" / "c_kpi.parquet").exists()
    from contracts.dashboard import DashboardSpec
    from contracts.common import load
    spec = load(DashboardSpec, out.outputs["spec"])
    assert "camembert" in " ".join(spec.warnings).lower() or "pie" in " ".join(spec.warnings).lower()


def test_run_fails_cleanly_on_missing_input(tmp_path):
    ctx = RunContext(run_id="run_t", agent="dashboard", inputs={"request": tmp_path / "nope.json", "result": tmp_path / "x",
                     "comparisons": tmp_path / "y", "data": tmp_path / "z"}, output_dir=tmp_path / "o",
                     journal=tmp_path / "audit.db")
    assert run(ctx).status == AgentStatus.FAILED


# ---------------------------------------------------------------- lab + notebook stay runnable
def test_lab_scenarios_all_run_in_both_languages():
    from dashboard_ai.lab.lab_dashboard import run_scenario, scenarios
    for lang in ("en", "fr"):
        for s in scenarios():
            spec, advice, frames = run_scenario(s, lang)
            assert spec.charts and set(frames) == {c.chart_id for c in spec.charts}


def test_notebook_is_valid_and_has_no_error_output():
    import json
    nb_path = REPO_ROOT / "dashboard_ai" / "notebooks" / "06_dashboard_intelligent.ipynb"
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    errors = [o for c in nb["cells"] if c["cell_type"] == "code" for o in c.get("outputs", []) if o["output_type"] == "error"]
    assert not errors


def test_data_file_without_contract_columns_degrades_to_kpi_card():
    req, res = make()
    spec, advice, frames = build_dashboard(req, res, None, pd.DataFrame({"dummy": [1.0]}))
    assert [c.chart_type for c in spec.charts] == [ChartType.KPI_CARD]
    assert frames["c_kpi"]["value"].iloc[0] == 1000.0
    assert IssueKind.DATA_MISMATCH in kinds(advice) and spec.warnings
