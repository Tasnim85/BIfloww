"""dashboard.py -- Step 6: build the dashboard spec (Samar).

Reads the analysis result and comparison report, picks the best chart type
for each metric/dimension combination, and writes a DashboardSpec contract.

Chart selection rules (automatic):
  - has comparison          -> bar  (color=period to show 2 bars side by side)
  - time dimension          -> line
  - 2+ dimensions           -> bar  (faceted; heatmap not in ChartType enum)
  - 1 dimension, numeric    -> bar
  - no dimension            -> kpi_card
  - comparison with warnings -> bar + warning strings in DashboardSpec.warnings

FIX (audit 2026-10-21): replaced non-existent Panel/Warning imports with the
real contracts: ChartSpec and DashboardSpec.warnings: list[str].
"""
from __future__ import annotations

import uuid
from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.analysis import AnalysisResult
from contracts.common import load, save
from contracts.comparisons import CheckStatus, ComparisonReport
from contracts.dashboard import ChartSpec, ChartType, DashboardSpec
from contracts.semantic import AnalysisRequest


def _pick_chart(request: AnalysisRequest, has_comparison: bool) -> ChartType:
    """Automatic chart-type selection rule engine.

    Uses only ChartType values defined in contracts.dashboard:
        kpi_card | bar | line | map | pie | table
    """
    dims = request.dimensions
    time_dims = {"order_date", "purchase_date", "date", "year", "month",
                 "quarter", "order_month"}
    is_time = any(d in time_dims for d in dims)

    if not dims:
        return ChartType.KPI_CARD
    if is_time:
        return ChartType.LINE
    # bar works for single/multi dim and for comparisons (color=period)
    return ChartType.BAR


def _extract_warnings(comparisons: ComparisonReport) -> list[str]:
    """Extract human-readable warning strings from the comparison report."""
    warnings: list[str] = []
    for check in comparisons.checks:
        if check.status in (CheckStatus.WARNING, CheckStatus.BLOCKING):
            prefix = "[BLOCKING] " if check.status == CheckStatus.BLOCKING else ""
            warnings.append(f"{prefix}{check.message}")
    if comparisons.proposed_fix:
        warnings.append(
            f"Suggested fix: {comparisons.proposed_fix.description}"
        )
    return warnings


def run(ctx: RunContext) -> AgentResult:
    """Dashboard step: generate the DashboardSpec from analysis + comparison."""
    try:
        request = load(AnalysisRequest, ctx.inputs["request"])
        result = load(AnalysisResult, ctx.inputs["result"])
        comparisons = load(ComparisonReport, ctx.inputs["comparisons"])
    except Exception as exc:
        ctx.log("build_spec", "FAILED", evidence={"error": str(exc)})
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.FAILED,
            message=f"Could not load inputs: {exc}",
        )

    has_comparison = request.compare_to is not None
    chart_type = _pick_chart(request, has_comparison)
    warnings = _extract_warnings(comparisons)

    # Primary chart: the main metric/dimension view
    charts: list[ChartSpec] = [
        ChartSpec(
            chart_id=f"c_{uuid.uuid4().hex[:6]}",
            chart_type=chart_type,
            title=f"{request.metric} -- {', '.join(request.dimensions) or 'Overall'}",
            data_file=str(ctx.inputs.get("data", "")),
            x=request.dimensions[0] if request.dimensions else None,
            y=request.metric.lower(),
            color="period" if has_comparison else None,
            reason=(
                f"Automatic selection: {'comparison' if has_comparison else chart_type.value} "
                f"for dims={request.dimensions}"
            ),
        )
    ]

    # KPI card (headline number) when there is at least one dimension chart
    if request.dimensions:
        charts.insert(0, ChartSpec(
            chart_id=f"c_{uuid.uuid4().hex[:6]}",
            chart_type=ChartType.KPI_CARD,
            title=f"{request.metric} total",
            data_file=str(ctx.inputs.get("data", "")),
            x=None,
            y=request.metric.lower(),
            color=None,
            reason="Headline KPI card always shown alongside dimension breakdown.",
        ))

    spec = DashboardSpec(
        title=f"{request.metric} -- {request.period.start[:7]}",
        question=request.question,
        kpi=f"{request.metric}@2.0",
        charts=charts,
        warnings=warnings,
    )

    spec_path = ctx.output("spec")
    save(spec, spec_path)

    ctx.log(
        "build_spec", "SUCCESS",
        outputs=[str(spec_path)],
        evidence={
            "chart_type": chart_type.value,
            "charts": len(charts),
            "warnings": len(warnings),
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"spec": spec_path},
        message=(
            f"Dashboard spec built: {chart_type.value}, "
            f"{len(charts)} chart(s), {len(warnings)} warning(s)."
        ),
    )
