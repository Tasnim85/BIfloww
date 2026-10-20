"""BO4-12 page: is this comparison honest? Display + user decision. No business logic."""
from datetime import date, timedelta

import matplotlib.pyplot as plt
import streamlit as st

from auditor.ui.data import UI_JOURNAL, base_run, journal_for, read, runs_with, source_badge, t, ui_lang
from comparisons.checker import record_decision, run as run_checker
from contracts.agent import RunContext
from contracts.common import Period, load, save
from contracts.comparisons import CheckStatus, ComparisonReport
from contracts.i18n import fmt, localize
from contracts.pipeline import RUNS_ROOT, context_for, output_path
from contracts.semantic import AnalysisRequest, KpiCatalog, load_yaml

ICON = {CheckStatus.OK: "✅", CheckStatus.WARNING: "⚠️", CheckStatus.BLOCKING: "⛔"}
CUSTOM_RUN = "ui_custom"


def _run_custom(base: str, metric: str, dims: list[str], cur: tuple[date, date],
                prev: tuple[date, date], use_llm: bool) -> None:
    """Run the real BO4-12 agent on a request typed in the UI, on the data of run `base`."""
    req = AnalysisRequest(question=t("cmp.typed"), metric=metric, dimensions=dims,
                          period=Period(start=cur[0].isoformat(), end=cur[1].isoformat()),
                          compare_to=Period(start=prev[0].isoformat(), end=prev[1].isoformat()))
    inputs = dict(context_for("comparisons", base).inputs)
    inputs["request"] = save(req, output_path(CUSTOM_RUN, "request", "request"))
    inputs["result"] = output_path(CUSTOM_RUN, "analysis", "result")         # none: values recomputed
    (RUNS_ROOT / CUSTOM_RUN / "base_run.txt").write_text(base, encoding="utf-8")
    ctx = RunContext(run_id=CUSTOM_RUN, agent="comparisons", inputs=inputs,
                     output_dir=RUNS_ROOT / CUSTOM_RUN / "comparisons",
                     params={"llm": use_llm, "language": ui_lang()}, journal=UI_JOURNAL)
    run_checker(ctx)


def _coverage_chart(run_id: str, report: ComparisonReport, request: AnalysisRequest):
    cov = read(base_run(run_id), "profiling.coverage")
    check = next((c for c in report.checks if c.kind.value == "coverage"), None)
    if cov is None or check is None:
        return None
    lo = min(request.period.start, request.compare_to.start)
    hi = max(request.period.end, request.compare_to.end)
    table = check.evidence.get("table")
    cov_table = next((x for x in cov.tables if x.table == table), cov.tables[0])
    days = [d for d in cov_table.days if lo <= d.date <= hi]
    bad = set(check.evidence.get("current", {}).get("incomplete_days", {})) | \
        set(check.evidence.get("previous", {}).get("incomplete_days", {}))
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.bar(range(len(days)), [d.rows for d in days],
           color=["#d62728" if d.date in bad else "#1f77b4" for d in days])
    thr = check.evidence.get("current", {}).get("threshold_rows")
    if thr:
        ax.axhline(thr, color="#d62728", linestyle="--", linewidth=0.8, label=t("cmp.threshold", thr=thr))
        ax.legend(loc="upper left", fontsize=8)
    step = max(1, len(days) // 12)
    ax.set_xticks(range(0, len(days), step), [days[i].date[5:] for i in range(0, len(days), step)], fontsize=8)
    ax.set_ylabel(t("cmp.per_day", table=cov_table.table))
    fig.tight_layout()
    return fig


def _default_periods(base: str) -> tuple[tuple[date, date], tuple[date, date]]:
    """Last month of the data compared with the month before (whatever the dataset)."""
    cov = read(base, "profiling.coverage")
    last = date.fromisoformat(cov.tables[0].last_day) if cov else date.today()
    cur_start = last.replace(day=1)
    prev_end = cur_start - timedelta(days=1)
    return (cur_start, last), (prev_end.replace(day=1), prev_end)


def _custom_form() -> None:
    bases = [r for r in runs_with("profiling", "coverage") if output_path(r, "etl", "warehouse").exists()]
    if not bases:
        st.info(t("cmp.no_base"))
        return
    base = st.selectbox(t("cmp.data_of"), bases, index=bases.index("run_001") if "run_001" in bases else 0)
    catalog = load_yaml(KpiCatalog, context_for("comparisons", base).inputs["catalog"])
    k1, k2 = st.columns(2)
    metric = k1.selectbox(t("cmp.kpi"), [k.name for k in catalog.kpis])
    dims = k2.multiselect(t("cmp.dims"), catalog.kpi(metric).allowed_dimensions)
    cur_default, prev_default = _default_periods(base)
    with st.form("custom"):
        c1, c2 = st.columns(2)
        cur = c1.date_input(t("cmp.period"), cur_default)
        prev = c2.date_input(t("cmp.compare_to"), prev_default)
        use_llm = st.checkbox(t("cmp.llm"), value=False)
        go = st.form_submit_button(t("cmp.launch"), type="primary")
    st.caption(t("cmp.default_hint"))
    if go and len(cur) == 2 and len(prev) == 2:
        with st.spinner(t("cmp.running")):
            _run_custom(base, metric, dims, cur, prev, use_llm)
        st.session_state["cmp_run"] = CUSTOM_RUN


def render() -> None:
    st.title(t("cmp.title"))
    st.caption(t("cmp.caption"))

    with st.expander(t("cmp.try_other"), expanded=False):
        _custom_form()

    choices = runs_with("comparisons", "report")
    if not choices:
        st.error(t("cmp.no_report"))
        return
    default = st.session_state.get("cmp_run", choices[0])
    run_id = st.radio(t("cmp.shown"), choices, index=choices.index(default) if default in choices else 0,
                      horizontal=True, format_func=lambda r: t("cmp.mine") if r == CUSTOM_RUN else r)
    report = localize(load(ComparisonReport, output_path(run_id, "comparisons", "report")), ui_lang())
    request = load(AnalysisRequest, output_path(run_id, "request", "request"))
    journal = journal_for(run_id)

    st.subheader(t("cmp.question"))
    st.write(t("cmp.question_text", metric=request.metric, start=request.period.start, end=request.period.end,
               cstart=request.compare_to.start, cend=request.compare_to.end))

    if not report.has_comparison:
        st.info(report.summary)
        return

    blocking = any(c.status == CheckStatus.BLOCKING for c in report.checks)
    (st.error if blocking else st.success)(t("cmp.misleading") if blocking else t("cmp.valid"))

    st.subheader(t("cmp.checks"))
    for c in report.checks:
        with st.expander(f"{ICON[c.status]} {t('kind.' + c.kind.value)} — {t('status.' + c.status.value)}",
                         expanded=c.status != CheckStatus.OK):
            st.write(c.message)
            st.json(c.evidence, expanded=False)

    fig = _coverage_chart(run_id, report, request)
    if fig is not None:
        table = next(c.evidence.get("table", "") for c in report.checks if c.kind.value == "coverage")
        st.subheader(t("cmp.coverage", table=table))
        st.pyplot(fig)
        plt.close(fig)
        st.caption(t("cmp.coverage_caption", rules=report.rules_version))

    fixes = ([report.proposed_fix] if report.proposed_fix else []) + report.alternatives
    if fixes:
        st.subheader(t("cmp.fixes"))
        cols = st.columns(len(fixes))
        for col, f, i in zip(cols, fixes, range(len(fixes))):
            with col:
                st.markdown(f"**{t('cmp.recommended') if i == 0 else t('cmp.alternative')} · {f.method.value}**")
                lang = ui_lang()
                st.metric(f"{f.period.start} → {f.period.end}", f"{fmt(f.value_current, 'num2', lang)} {f.unit}",
                          fmt(f.change_pct, "spct", lang) if f.change_pct is not None else None)
                st.caption(t("cmp.against", prev=f.value_previous, unit=f.unit,
                             start=f.compare_to.start, end=f.compare_to.end))
                st.write(f.justification)

    st.subheader(t("cmp.summary"))
    st.caption(source_badge(report.summary_source))
    st.info(report.summary)

    st.subheader(t("cmp.decision"))
    st.write(t("cmp.state", state=t("decision." + report.user_decision.value))
             + (f" ({report.chosen_fix.value})" if report.chosen_fix else ""))
    if fixes:
        cols = st.columns(len(fixes) + 1)
        for col, f in zip(cols, fixes):
            if col.button(t("cmp.accept", method=f.method.value), key=f"acc_{f.method.value}"):
                record_decision(run_id, "accepted", f.method.value, journal=journal)
                st.rerun()
        if cols[-1].button(t("cmp.reject")):
            record_decision(run_id, "rejected", journal=journal)
            st.rerun()
        st.caption(t("cmp.decision_caption"))
