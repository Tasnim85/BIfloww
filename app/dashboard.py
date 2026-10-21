"""dashboard.py -- Step 6: build the dashboard spec (Samar).

Reads the analysis result and comparison report, picks the best chart type
for each metric/dimension combination, and writes a DashboardSpec contract.

Chart selection rules (automatic):
  - no dimension            -> kpi_card
  - 3+ dimensions           -> table
  - time dimension          -> line
  - 2 dimensions            -> bar (grouped/faceted: x=dim1, color=dim2)
  - comparison              -> bar (x=dim1, color=period to show periods side by side)
  - 1 dimension, categorical-> bar
  - comparison with warnings -> bar + warning strings in DashboardSpec.warnings
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
    if len(dims) >= 3:
        return ChartType.TABLE
    if is_time:
        return ChartType.LINE
    # Bar chart handles single/multi-dimensions (grouped via color) and comparisons
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

    # Determine dimensions binding:
    # x = primary dimension
    # color = comparison period OR secondary dimension (grouped bar)
    x_col = request.dimensions[0] if request.dimensions else None
    color_col = None
    if has_comparison:
        color_col = "period"
    elif len(request.dimensions) > 1:
        color_col = request.dimensions[1]

    reason_desc = (
        "comparison side-by-side" if has_comparison
        else f"grouped {chart_type.value} across {', '.join(request.dimensions)}" if color_col
        else f"{chart_type.value} for {request.dimensions}"
    )

    # Primary chart: the main metric/dimension view
    charts: list[ChartSpec] = [
        ChartSpec(
            chart_id=f"c_{uuid.uuid4().hex[:6]}",
            chart_type=chart_type,
            title=f"{request.metric} -- {', '.join(request.dimensions) or 'Overall'}",
            data_file=str(ctx.inputs.get("data", "")),
            x=x_col,
            y=request.metric.lower(),
            color=color_col,
            reason=f"Automatic selection: {reason_desc}",
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
        inputs=[
            str(ctx.inputs["request"]),
            str(ctx.inputs["result"]),
            str(ctx.inputs["comparisons"]),
        ],
        outputs=[str(spec_path)],
        rule_version="dashboard:spec@1.1",
        evidence={
            "chart_type": chart_type.value,
            "charts": [c.chart_type.value for c in charts],
            "x": x_col,
            "color": color_col,
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
