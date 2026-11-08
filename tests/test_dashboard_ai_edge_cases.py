"""Edge case and robustness tests for dashboard_ai (BO4 Step 6).

Verifies graceful degradation and safe handling of:
- Missing columns (dimension, value, period)
- Empty DataFrames (0 rows with or without columns)
- Single row / single unique value dimension
- Missing period column when comparison requested
- NaN values in value and dimension columns
- All-zero or negative values (division-by-zero guards)
- Integration via agent.run with edge case data
"""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.analysis import AnalysisResult, ValidationCheck
from contracts.common import Period, save, load
from contracts.comparisons import ComparisonReport, CheckStatus
from contracts.dashboard import ChartType, DashboardSpec
from contracts.semantic import AnalysisRequest

from dashboard_ai.agent import build_dashboard, run
from dashboard_ai.models import IssueKind


def _make_req_res(question="Revenue by state", dims=("customer_state",), compare=False):
    req = AnalysisRequest(
        metric="Revenue",
        dimensions=list(dims),
        period=Period(start="2018-08-01", end="2018-08-31"),
        compare_to=Period(start="2018-07-01", end="2018-07-31") if compare else None,
        question=question,
    )
    res = AnalysisResult(
        request=req,
        kpi="Revenue@2.0",
        sql="SELECT customer_state, SUM(val) FROM tbl GROUP BY 1",
        rows=10,
        value_current=12345.67,
        value_previous=10000.0 if compare else None,
        unit="BRL",
        validations=[ValidationCheck(name="valid", passed=True, detail="ok")],
    )
    return req, res


def test_missing_dimension_column_degrades_to_kpi_card():
    req, res = _make_req_res()
    df = pd.DataFrame({"wrong_column": ["SP", "RJ"], "value": [100.0, 200.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 1
    assert spec.charts[0].chart_type == ChartType.KPI_CARD
    assert any("missing: customer_state" in w for w in spec.warnings)
    assert not advice.comparison_shown
    assert "c_kpi" in frames
    assert "c_main" not in frames


def test_missing_value_column_degrades_to_kpi_card():
    req, res = _make_req_res()
    df = pd.DataFrame({"customer_state": ["SP", "RJ"], "Revenue": [100.0, 200.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 1
    assert spec.charts[0].chart_type == ChartType.KPI_CARD
    assert any("missing: value" in w for w in spec.warnings)
    assert "c_kpi" in frames


def test_completely_empty_dataframe_no_columns():
    req, res = _make_req_res()
    df = pd.DataFrame()
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 1
    assert spec.charts[0].chart_type == ChartType.KPI_CARD
    assert any("missing: customer_state, value" in w for w in spec.warnings)


def test_empty_dataframe_with_correct_columns():
    req, res = _make_req_res()
    df = pd.DataFrame(columns=["customer_state", "value"])
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 2
    assert spec.charts[0].chart_type == ChartType.KPI_CARD
    assert spec.charts[1].chart_type == ChartType.BAR
    assert len(frames["c_main"]) == 0


def test_missing_period_when_comparison_requested():
    req, res = _make_req_res(compare=True)
    df = pd.DataFrame({"customer_state": ["SP", "RJ"], "value": [100.0, 200.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert not advice.comparison_shown
    assert "period" not in frames["c_main"].columns


def test_single_row_dataframe():
    req, res = _make_req_res()
    df = pd.DataFrame({"customer_state": ["SP"], "value": [500.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    main = next(c for c in spec.charts if c.chart_id == "c_main")
    assert main.chart_type == ChartType.BAR
    assert len(frames["c_main"]) == 1


def test_nan_in_value_column():
    req, res = _make_req_res()
    df = pd.DataFrame({"customer_state": ["SP", "RJ", "MG"], "value": [100.0, np.nan, 200.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 2
    assert "c_main" in frames
    assert not frames["c_kpi"].empty


def test_nan_in_dimension_column():
    req, res = _make_req_res()
    df = pd.DataFrame({"customer_state": ["SP", np.nan, "RJ"], "value": [100.0, 50.0, 200.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 2
    assert "c_main" in frames


def test_dimension_with_single_unique_value():
    req, res = _make_req_res()
    df = pd.DataFrame({"customer_state": ["SP"] * 5, "value": [10.0, 20.0, 30.0, 40.0, 50.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    main = next(c for c in spec.charts if c.chart_id == "c_main")
    assert main.chart_type == ChartType.BAR


def test_all_zero_values_handled_without_division_by_zero():
    req, res = _make_req_res()
    df = pd.DataFrame({"customer_state": ["SP", "RJ", "MG"], "value": [0.0, 0.0, 0.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 2
    assert frames["c_kpi"]["value"].iloc[0] == 12345.67


def test_negative_values_block_pie_chart():
    req, res = _make_req_res(question="Revenue by state as a pie chart")
    df = pd.DataFrame({"customer_state": ["SP", "RJ", "MG"], "value": [-50.0, 100.0, 150.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    main = next(c for c in spec.charts if c.chart_id == "c_main")
    assert main.chart_type == ChartType.BAR
    assert any("pie" in w.lower() or "camembert" in w.lower() for w in spec.warnings)


def test_two_dimensions_with_one_missing():
    req, res = _make_req_res(dims=["customer_state", "customer_city"])
    df = pd.DataFrame({"customer_state": ["SP", "RJ"], "value": [100.0, 200.0]})
    spec, advice, frames = build_dashboard(req, res, None, df)

    assert len(spec.charts) == 1
    assert spec.charts[0].chart_type == ChartType.KPI_CARD
    assert any("customer_city" in w for w in spec.warnings)


def test_agent_run_on_edge_case_missing_column(tmp_path):
    req, res = _make_req_res()
    inputs = {
        "request": save(req, tmp_path / "req.json"),
        "result": save(res, tmp_path / "res.json"),
        "comparisons": save(ComparisonReport(has_comparison=False), tmp_path / "cmp.json"),
        "data": tmp_path / "result.parquet",
    }
    pd.DataFrame({"invalid_col": [1, 2], "val": [10, 20]}).to_parquet(inputs["data"])

    ctx = RunContext(
        run_id="run_edge",
        agent="dashboard",
        inputs=inputs,
        output_dir=tmp_path / "out",
        params={"lang": "en"},
        journal=tmp_path / "audit.db",
    )
    result = run(ctx)

    assert result.status == AgentStatus.SUCCESS
    spec = load(DashboardSpec, result.outputs["spec"])
    assert len(spec.charts) == 1
    assert spec.charts[0].chart_type == ChartType.KPI_CARD
    assert (tmp_path / "out" / "c_kpi.parquet").exists()
