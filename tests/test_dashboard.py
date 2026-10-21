"""test_dashboard.py -- Tests for app/dashboard.py (Step 6, Samar).

Tests _pick_chart() for all branches and run() with stubbed contracts.

BUG-01 FIX VERIFICATION: Confirms that dashboard no longer imports
non-existent Panel/Warning, but uses correct ChartSpec/DashboardSpec.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.common import Period
from contracts.dashboard import ChartType
from contracts.semantic import AnalysisRequest

_DEFAULT_PERIOD = Period(start="2017-08-01", end="2017-08-31")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(**kwargs) -> AnalysisRequest:
    defaults = dict(
        question="Revenue by state in August",
        metric="Revenue",
        dimensions=[],
        period=_DEFAULT_PERIOD,
        compare_to=None,
        filters=[],
        confidence=0.9,
        matched_terms={},
    )
    defaults.update(kwargs)
    return AnalysisRequest(**defaults)


# ---------------------------------------------------------------------------
# _pick_chart
# ---------------------------------------------------------------------------

class TestPickChart:
    """T-DASH-01..05: automatic chart-type selection."""

    def test_no_dims_gives_kpi_card(self):
        """T-DASH-01: no dimensions -> kpi_card."""
        from app.dashboard import _pick_chart
        req = _make_request(dimensions=[], compare_to=None)
        assert _pick_chart(req, has_comparison=False) == ChartType.KPI_CARD

    def test_time_dim_gives_line(self):
        """T-DASH-02: time dimension (order_month) -> line."""
        from app.dashboard import _pick_chart
        req = _make_request(dimensions=["order_month"], compare_to=None)
        assert _pick_chart(req, has_comparison=False) == ChartType.LINE

    def test_non_time_dim_gives_bar(self):
        """T-DASH-03: non-time dim (customer_state) -> bar."""
        from app.dashboard import _pick_chart
        req = _make_request(dimensions=["customer_state"], compare_to=None)
        assert _pick_chart(req, has_comparison=False) == ChartType.BAR

    def test_comparison_gives_bar(self):
        """T-DASH-04: comparison present -> bar (color=period)."""
        from app.dashboard import _pick_chart
        compare_period = Period(start="2017-07-01", end="2017-07-31")
        req = _make_request(dimensions=["customer_state"], compare_to=compare_period)
        assert _pick_chart(req, has_comparison=True) == ChartType.BAR

    def test_multiple_dims_gives_bar(self):
        """T-DASH-05: 2 dims -> bar (grouped/faceted via color)."""
        from app.dashboard import _pick_chart
        req = _make_request(
            dimensions=["customer_state", "payment_type"], compare_to=None
        )
        assert _pick_chart(req, has_comparison=False) == ChartType.BAR

    def test_three_or_more_dims_gives_table(self):
        """T-DASH-05b: 3+ dims -> table view."""
        from app.dashboard import _pick_chart
        req = _make_request(
            dimensions=["customer_state", "payment_type", "product_category"], compare_to=None
        )
        assert _pick_chart(req, has_comparison=False) == ChartType.TABLE


# ---------------------------------------------------------------------------
# Import smoke test (BUG-01 guard)
# ---------------------------------------------------------------------------

def test_dashboard_imports_correctly():
    """T-DASH-06: BUG-01 guard -- import succeeds with correct contracts."""
    from app.dashboard import _pick_chart, run  # noqa: F401
    from contracts.dashboard import ChartSpec, DashboardSpec  # noqa: F401

    valid = {ct.value for ct in ChartType}
    assert "kpi_card" in valid
    assert "bar" in valid
    assert "line" in valid
    assert "grouped_bar" not in valid   # was wrongly imported before the fix
    assert "heatmap" not in valid


# ---------------------------------------------------------------------------
# run() integration test
# ---------------------------------------------------------------------------

class TestDashboardRun:
    """T-DASH-07: run() with fully stubbed inputs."""

    def test_run_produces_valid_dashboard_spec(self, tmp_path):
        """T-DASH-07: run() writes a valid DashboardSpec JSON file."""
        from contracts.agent import AgentStatus, RunContext
        from contracts.common import Period, save
        from contracts.comparisons import ComparisonReport
        from contracts.dashboard import DashboardSpec

        run_id = str(uuid.uuid4())
        runs_root = tmp_path / "runs"

        # --- request ---
        req_dir = runs_root / run_id / "request"
        req_dir.mkdir(parents=True)
        request = AnalysisRequest(
            question="Revenue by state in August",
            metric="Revenue",
            dimensions=["customer_state"],
            period=Period(start="2017-08-01", end="2017-08-31"),
            compare_to=None,
            filters=[],
            confidence=0.85,
            matched_terms={"Revenue": "revenue"},
        )
        save(request, req_dir / "analysis_request.json")

        # --- analysis result ---
        analysis_dir = runs_root / run_id / "analysis"
        analysis_dir.mkdir(parents=True)
        from contracts.analysis import AnalysisResult, ValidationCheck
        result = AnalysisResult(
            request=request,
            kpi="Revenue@2.0",
            sql="SELECT customer_state, SUM(payment_value) FROM fact_payments GROUP BY 1",
            rows=5,
            value_current=123456.78,
            unit="BRL",
            validations=[
                ValidationCheck(name="grain_matches_kpi", passed=True, detail="grain ok"),
            ],
        )
        save(result, analysis_dir / "analysis_result.json")

        # --- comparison report (no comparison) ---
        comp_dir = runs_root / run_id / "comparisons"
        comp_dir.mkdir(parents=True)
        comparisons = ComparisonReport(has_comparison=False, checks=[])
        save(comparisons, comp_dir / "comparison_report.json")

        # --- data placeholder ---
        data_path = analysis_dir / "result.parquet"
        data_path.write_text("")

        # --- dashboard output dir ---
        dash_dir = runs_root / run_id / "dashboard"
        dash_dir.mkdir(parents=True)

        # RunContext uses output_dir (not outputs dict) and agent as str
        ctx = RunContext(
            run_id=run_id,
            agent="dashboard",
            output_dir=dash_dir,
            inputs={
                "request":     req_dir / "analysis_request.json",
                "result":      analysis_dir / "analysis_result.json",
                "comparisons": comp_dir / "comparison_report.json",
                "data":        data_path,
            },
        )

        from app.dashboard import run
        agent_result = run(ctx)

        assert agent_result.status == AgentStatus.SUCCESS
        spec_path = dash_dir / "dashboard_spec.json"
        assert spec_path.exists(), "dashboard_spec.json not written"

        spec = DashboardSpec.model_validate_json(
            spec_path.read_text(encoding="utf-8")
        )
        assert spec.question == "Revenue by state in August"
        assert spec.kpi == "Revenue@2.0"
        assert len(spec.charts) >= 1

        chart_types = {c.chart_type for c in spec.charts}
        assert ChartType.BAR in chart_types        # dimension chart
        assert ChartType.KPI_CARD in chart_types   # headline card
