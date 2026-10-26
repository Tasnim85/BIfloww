"""BO4 Step 6 -- intelligent dashboard agent.

    run(ctx)             called by the orchestrator (same inputs/outputs as app.dashboard:run)
    build_dashboard()    pure function (no files): used by the lab, the notebook and the tests

What it adds to the first version of the dashboard step:
  1. every chart type is scored on THIS data and the best eligible one is chosen;
  2. a chart explicitly asked for is refused (with the reason) when it would mislead;
  3. the comparison report (BO4-12) is respected: a blocked comparison is not drawn;
  4. visual traps are flagged (base effect, dominant category, hole in a time axis, ...);
  5. each chart gets its prepared data file and a side-car `chart_advice.json` for the Auditor.
"""
from pathlib import Path

import pandas as pd

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.analysis import AnalysisResult
from contracts.common import load, save
from contracts.comparisons import CheckStatus, ComparisonReport, UserDecision
from contracts.dashboard import ChartSpec, ChartType, DashboardSpec
from contracts.semantic import AnalysisRequest
from dashboard_ai.intent import detect_intent, detect_requested_chart
from dashboard_ai.messages import t
from dashboard_ai.misleading import requested_refused, visual_issues
from dashboard_ai.models import (ChartAdvice, ChartCandidate, ChartDecision, IssueKind, VisualIssue)
from dashboard_ai.prepare import prepare
from dashboard_ai.profile import build_profile, is_additive
from dashboard_ai.rules import DEFAULT, RULES_VERSION, Rules
from dashboard_ai.selector import score_candidates


def build_dashboard(request: AnalysisRequest, result: AnalysisResult, report: ComparisonReport | None,
                    df: pd.DataFrame, *, rules: Rules = DEFAULT, lang: str = "en", data_dir: Path | str = ".",
                    additive: bool | None = None) -> tuple[DashboardSpec, ChartAdvice, dict[str, pd.DataFrame]]:
    data_dir = Path(data_dir)
    additive = is_additive(result.sql) if additive is None else additive
    dims = request.dimensions

    missing = [c for c in [*dims, "value"] if c not in df.columns]
    if missing:                      # degrade, never crash: the headline KPI only needs AnalysisResult
        issue = VisualIssue(kind=IssueKind.DATA_MISMATCH, status=CheckStatus.WARNING,
                            message=t("issue.data_mismatch", lang, cols=", ".join(missing)), evidence={"missing": missing})
        kpi = ChartSpec(chart_id="c_kpi", chart_type=ChartType.KPI_CARD, title=t("title.total", lang, metric=request.metric),
                        data_file=str(data_dir / "c_kpi.parquet"), y="value", reason=t("why.kpi", lang))
        decision = ChartDecision(chart_id="c_kpi", chosen=ChartType.KPI_CARD, intent="none", issues=[issue],
                                 candidates=[ChartCandidate(chart_type=ChartType.KPI_CARD, score=100, eligible=True,
                                                            reasons=[t("why.kpi", lang)])])
        spec = DashboardSpec(title=f"{request.metric} -- {request.period.start[:7]}", question=request.question,
                             kpi=result.kpi, charts=[kpi], warnings=[issue.message])
        return (spec, ChartAdvice(rules_version=RULES_VERSION, comparison_shown=False, decisions=[decision]),
                {"c_kpi": pd.DataFrame({"value": [result.value_current]})})

    profile = build_profile(df, dims, metric=request.metric, unit=result.unit, additive=additive)

    # ---- is the comparison allowed on screen? (nothing is applied without Sarra's decision)
    asked_cmp = request.compare_to is not None and "period" in df.columns
    blocking = [c for c in (report.checks if report else []) if c.status == CheckStatus.BLOCKING]
    decision = report.user_decision if report else UserDecision.PENDING
    shown = asked_cmp and not (blocking and decision != UserDecision.REJECTED)
    fix = report.proposed_fix if report else None
    adjusted = bool(blocking and decision == UserDecision.ACCEPTED and fix)

    # ---- what does the question want, which chart fits?
    intent = detect_intent(request.question, n_dims=len(dims), temporal=profile.temporal, has_comparison=shown)
    requested = detect_requested_chart(request.question)
    candidates = score_candidates(profile, intent, requested, rules, lang, shown)
    chosen = candidates[0].chart_type

    issues: list[VisualIssue] = []
    if requested and (refused := requested_refused(requested, chosen, candidates, lang)):
        issues.append(refused)

    # ---- headline numbers (adjusted ones if Sarra accepted the proposed fix)
    v_cur, v_prev, pct = result.value_current, result.value_previous, result.change_pct
    if adjusted:
        v_cur, v_prev, pct = fix.value_current, fix.value_previous, fix.change_pct
    elif not shown:
        v_prev, pct = None, None

    data, x, color, prep_issues = prepare(df, chosen, profile, rules, lang, shown)
    issues += prep_issues + visual_issues(df, profile, chosen, rules, lang, v_cur, v_prev)

    for c in (report.checks if report else []):
        if c.status == CheckStatus.BLOCKING:
            issues.append(VisualIssue(kind=IssueKind.COMPARISON_BLOCKED, status=CheckStatus.BLOCKING,
                          message=t("issue.cmp_blocked", lang, msg=c.message), evidence=c.evidence))
        elif c.status == CheckStatus.WARNING:
            issues.append(VisualIssue(kind=IssueKind.COMPARISON_WARNING, status=CheckStatus.WARNING,
                          message=t("issue.cmp_warning", lang, msg=c.message), evidence=c.evidence))
    if adjusted:
        issues.append(VisualIssue(kind=IssueKind.COMPARISON_ADJUSTED, status=CheckStatus.WARNING,
                      message=t("issue.cmp_adjusted", lang, desc=fix.description), evidence={"method": fix.method.value}))

    # ---- charts
    frames: dict[str, pd.DataFrame] = {}
    specs: list[ChartSpec] = []
    decisions: list[ChartDecision] = []

    headline = t("title.total", lang, metric=request.metric)
    if pct is not None:
        headline += f" ({t('title.vs', lang, pct=pct)})"
    kpi_reason = t("why.kpi", lang) if not dims else t("kpi.has_dims", lang)
    kpi_value = v_cur if v_cur is not None else profile.total
    frames["c_kpi"] = pd.DataFrame({"value": [kpi_value]})
    specs.append(ChartSpec(chart_id="c_kpi", chart_type=ChartType.KPI_CARD, title=headline,
                           data_file=str(data_dir / "c_kpi.parquet"), y="value", reason=kpi_reason))
    decisions.append(ChartDecision(chart_id="c_kpi", chosen=ChartType.KPI_CARD, intent=intent.value,
                                   candidates=[ChartCandidate(chart_type=ChartType.KPI_CARD, score=100, eligible=True,
                                                              reasons=[kpi_reason])],
                                   issues=[] if dims else issues))      # no dimension: the KPI card IS the chart

    if dims:
        best = candidates[0]
        reason = " ".join(best.reasons)
        if refused_issue := next((i for i in issues if i.kind == IssueKind.REQUESTED_CHART_REFUSED), None):
            reason += " " + refused_issue.message
        frames["c_main"] = data
        specs.append(ChartSpec(chart_id="c_main", chart_type=chosen,
                               title=f"{request.metric} -- {', '.join(dims)}",
                               data_file=str(data_dir / "c_main.parquet"), x=x, y="value", color=color, reason=reason))
        decisions.append(ChartDecision(chart_id="c_main", chosen=chosen, intent=intent.value, requested=requested,
                                       candidates=candidates, issues=issues))

    warnings: list[str] = []
    for i in issues:
        w = ("[BLOCKING] " if i.status == CheckStatus.BLOCKING else "") + i.message
        if w not in warnings:
            warnings.append(w)
    if fix and decision == UserDecision.PENDING and blocking:
        warnings.append(f"Suggested fix: {fix.description}")

    spec = DashboardSpec(title=f"{request.metric} -- {request.period.start[:7]}", question=request.question,
                         kpi=result.kpi, charts=specs, warnings=warnings)
    advice = ChartAdvice(rules_version=RULES_VERSION, comparison_shown=shown, decisions=decisions)
    return spec, advice, frames


def run(ctx: RunContext) -> AgentResult:
    try:
        request = load(AnalysisRequest, ctx.inputs["request"])
        result = load(AnalysisResult, ctx.inputs["result"])
        report = load(ComparisonReport, ctx.inputs["comparisons"])
        df = pd.read_parquet(ctx.inputs["data"])
    except Exception as exc:
        ctx.log("build_spec", "FAILED", evidence={"error": str(exc)})
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED,
                           message=f"Could not load inputs: {exc}")

    rules = Rules(**ctx.params.get("rules", {}))
    lang = ctx.params.get("lang", "en")
    spec, advice, frames = build_dashboard(request, result, report, df, rules=rules, lang=lang,
                                           data_dir=ctx.output_dir)
    for chart in spec.charts:
        path = Path(chart.data_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        frames[chart.chart_id].to_parquet(path, index=False)

    spec_path = save(spec, ctx.output("spec"))
    advice_path = save(advice, ctx.output_dir / "chart_advice.json")

    for d in advice.decisions:
        ctx.log("chart_selected", d.chosen.value, rule_version=RULES_VERSION, outputs=[str(spec_path)],
                evidence={"chart_id": d.chart_id, "intent": d.intent, "requested": d.requested.value if d.requested else None,
                          "ranking": [(c.chart_type.value, c.score, c.eligible) for c in d.candidates],
                          "rules": rules.as_evidence()})
        for i in d.issues:
            ctx.log("visual_issue", f"{i.status.value.upper()}: {i.kind.value}", rule_version=RULES_VERSION,
                    evidence={"message": i.message, **i.evidence})

    n_issues = sum(len(d.issues) for d in advice.decisions)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       outputs={"spec": spec_path},
                       message=f"Dashboard built: {', '.join(c.chart_type.value for c in spec.charts)}; {n_issues} visual issue(s).")
