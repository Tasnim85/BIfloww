"""dashboard.py — Step 6: build the dashboard spec (Samar).

Reads the analysis result and comparison report, picks the best chart type
for each metric/dimension combination, and writes a DashboardSpec contract.

Chart selection rules (automatic):
  - 1 dimension, numeric metric  → bar_chart
  - time dimension               → line_chart
  - 2+ dimensions                → heatmap
  - comparison present           → grouped_bar_chart
  - comparison with warnings     → grouped_bar_chart + warning panel
"""
from __future__ import annotations

from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import load, save
from contracts.comparisons import ComparisonReport
from contracts.dashboard import ChartType, DashboardSpec, Panel, Warning
from contracts.semantic import AnalysisRequest
from contracts.analysis import AnalysisResult


def _pick_chart(request: AnalysisRequest, has_comparison: bool) -> ChartType:
    """Automatic chart-type selection rule engine."""
    dims = request.dimensions
    time_dims = {"order_date", "purchase_date", "date", "year", "month", "quarter"}
    is_time = any(d in time_dims for d in dims)

    if has_comparison:
        return ChartType.GROUPED_BAR
    if is_time:
        return ChartType.LINE
    if len(dims) >= 2:
        return ChartType.HEATMAP
    return ChartType.BAR


def run(ctx: RunContext) -> AgentResult:
    """Dashboard step: generate the DashboardSpec from analysis + comparison results."""
    try:
        request = load(AnalysisRequest, ctx.inputs["request"])
        result  = load(AnalysisResult,  ctx.inputs["result"])
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

    warnings: list[Warning] = []
    for check in comparisons.checks:
        if check.status != "PASSED":
            warnings.append(Warning(
                level="error" if check.status == "BLOCKING" else "warning",
                message=check.message,
                fix=comparisons.proposed_fix.description if comparisons.proposed_fix else None,
            ))

    panels: list[Panel] = [
        Panel(
            title=f"{request.metric} — {', '.join(request.dimensions) or 'Overall'}",
            chart_type=chart_type,
            metric=request.metric,
            dimensions=request.dimensions,
            period=request.period.model_dump(),
            compare_to=request.compare_to.model_dump() if request.compare_to else None,
            data_file=str(ctx.inputs.get("data", "")),
        )
    ]

    spec = DashboardSpec(
        run_id=ctx.run_id,
        question=request.question,
        panels=panels,
        warnings=warnings,
    )

    spec_path = ctx.output("spec")
    save(spec, spec_path)

    ctx.log(
        "build_spec", "SUCCESS",
        outputs=[str(spec_path)],
        evidence={
            "chart_type": chart_type,
            "panels": len(panels),
            "warnings": len(warnings),
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"spec": spec_path},
        message=f"Dashboard spec built: {chart_type}, {len(warnings)} warning(s).",
    )
