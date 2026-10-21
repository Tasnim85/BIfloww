"""Embeddable blocks of Tasnim's part, for the pipeline's RESULT screen (app/, Samar).

The final product is one screen per run (question -> pipeline -> dashboard). These
functions draw Tasnim's parts INSIDE that screen. Each takes the run id (and the
journal of that run) and draws one block. Display only: the agents do the work.

    trust_badge(run_id, journal)          header: can this result be trusted?
    comparison_banner(run_id, journal)    BO4-12: warning + user choice, BEFORE the charts;
                                          returns the periods the dashboard must use
    audit_panel(run_id, journal)          decisions, anomalies, integrity, drift of the run
    why_box(run_id, journal)              "why?" questions about this run

`key` makes the widgets unique when a block is used twice on one screen.
"""
from pathlib import Path

import streamlit as st

from auditor.ui.data import llm_status, read, source_badge, t, ui_lang
from auditor.why import WhyAgent
from comparisons.checker import record_decision
from comparisons.values import dashboard_periods
from contracts.audit import read_events, verify_journal
from contracts.common import Period
from contracts.i18n import fmt
from contracts.comparisons import CheckStatus, UserDecision

ROUTINE = {"OK", "PASSED", "computed in SQL", "answered (template)"}


# ---- 1. Header badge --------------------------------------------------------------
def trust_badge(run_id: str, journal: Path, key: str = "badge") -> None:
    integrity = verify_journal(journal)
    cmp = read(run_id, "comparisons.report")
    drift = read(run_id, "auditor.drift")
    expl = read(run_id, "auditor.explanations")

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(t("badge.journal_ok" if integrity.ok else "badge.journal_bad", n=integrity.entries_checked))
    if cmp is None or not cmp.has_comparison:
        c2.markdown(t("badge.cmp_none"))
    else:
        blocking = any(c.status == CheckStatus.BLOCKING for c in cmp.checks)
        state = {UserDecision.ACCEPTED: "cmp_adjusted", UserDecision.REJECTED: "cmp_as_asked",
                 UserDecision.PENDING: "cmp_pending"}[cmp.user_decision]
        c2.markdown(t(f"badge.{state}" if blocking else "badge.cmp_valid"))
    if drift is None or drift.status == "not_available":
        c3.markdown(t("badge.drift_none"))
    else:
        c3.markdown(t("badge.drift", icon="✅" if drift.status == "stable" else "⚠️",
                      status=t(f"drift_status.{drift.status}")))
    n = sum(e.is_anomaly for e in expl.explanations) if expl else 0
    c4.markdown(t("badge.anomalies", n=n) if expl else t("badge.anomalies_none"))


# ---- 2. BO4-12 banner -------------------------------------------------------------
def comparison_banner(run_id: str, journal: Path, key: str = "banner") -> tuple[Period, Period] | None:
    """Draws the BO4-12 verdict and the user's choice. Returns the (period, compare_to) the
    dashboard must use, or None while the user has not decided on a blocked comparison."""
    report = read(run_id, "comparisons.report")
    request = read(run_id, "request.request")
    if request is None:
        return None
    periods, _ = dashboard_periods(report, request)        # the same rule as the API
    if request.compare_to is None or report is None or not report.has_comparison:
        return periods

    fixes = ([report.proposed_fix] if report.proposed_fix else []) + report.alternatives
    blocking = any(c.status == CheckStatus.BLOCKING for c in report.checks)

    if report.user_decision == UserDecision.ACCEPTED and report.chosen_fix:
        f = next(x for x in fixes if x.method == report.chosen_fix)
        st.success(t("banner.adjusted", method=f.method.value, what=f.description, cur=f.value_current,
                     prev=f.value_previous, unit=f.unit, chg=f.change_pct))
        if st.button(t("banner.review"), key=f"{key}_undo"):
            record_decision(run_id, "pending", journal=journal)
            st.rerun()
        return periods
    if report.user_decision == UserDecision.REJECTED:
        if blocking:
            st.warning(t("banner.shown_as_asked",
                         msg=next(c.message for c in report.checks if c.status == CheckStatus.BLOCKING)))
        if st.button(t("banner.review"), key=f"{key}_undo"):
            record_decision(run_id, "pending", journal=journal)
            st.rerun()
        return periods
    if not blocking:
        warnings = [c.message for c in report.checks if c.status == CheckStatus.WARNING]
        if warnings:
            st.info(t("banner.note", msgs=" ".join(warnings)))
        if not fixes:
            return periods

    (st.error if blocking else st.info)(
        t("banner.misleading" if blocking else "banner.adjustable", source=source_badge(report.summary_source)))
    st.write(report.summary)
    cols = st.columns(len(fixes) + 1)
    for col, f, i in zip(cols, fixes, range(len(fixes))):
        label = f"{'✔ ' if i == 0 else ''}{f.description.split(':')[0].strip()} ({fmt(f.change_pct, 'spct', ui_lang())})"
        if col.button(label, key=f"{key}_{f.method.value}", type="primary" if i == 0 else "secondary"):
            record_decision(run_id, "accepted", f.method.value, journal=journal)
            st.rerun()
    if cols[-1].button(t("banner.keep"), key=f"{key}_reject"):
        record_decision(run_id, "rejected", journal=journal)
        st.rerun()
    st.caption(t("banner.waiting"))
    return periods


# ---- 3. Audit panel -----------------------------------------------------------------
def audit_panel(run_id: str, journal: Path, key: str = "audit") -> None:
    events = [e for e in read_events(journal, run_id=run_id)
              if not e.step.startswith("llm:") and e.step != "why_answer"]
    tabs = st.tabs([t("audit.decisions"), t("audit.anomalies"), t("audit.integrity"), t("audit.drift")])

    with tabs[0]:
        if not events:
            st.info(t("audit.no_decisions"))
        notable_only = st.checkbox(t("audit.notable_only"), value=True, key=f"{key}_notable")
        for agent in dict.fromkeys(e.agent for e in events):
            rows = [e for e in events if e.agent == agent and (not notable_only or e.decision not in ROUTINE)]
            if not rows:
                continue
            st.markdown(f"**{agent}**")
            for e in rows:
                with st.expander(f"#{e.entry_id} · {e.step} · {e.decision}"):
                    st.write(t("audit.rule", rule=e.rule_version or "-"))
                    st.json(e.evidence, expanded=False)

    with tabs[1]:
        expl = read(run_id, "auditor.explanations")
        if expl is None:
            st.info(t("audit.no_shap"))
        else:
            for e in [x for x in expl.explanations if x.is_anomaly][:5]:
                with st.expander(f"{e.row_key} · score {e.anomaly_score:.3f}"):
                    st.write(e.narrative)
            st.caption(t("audit.top5"))

    with tabs[2]:
        rep = verify_journal(journal)
        (st.success if rep.ok else st.error)(
            t("audit.integrity_ok", n=rep.entries_checked) if rep.ok
            else t("audit.integrity_bad", problem=rep.problem, n=rep.entries_checked))

    with tabs[3]:
        drift = read(run_id, "auditor.drift")
        if drift is None:
            st.info(t("audit.no_drift"))
        else:
            {"stable": st.success, "not_available": st.info}.get(drift.status, st.warning)(drift.narrative)


# ---- 4. "Why?" box ----------------------------------------------------------------
def why_box(run_id: str, journal: Path, suggestions: list[str] | None = None, key: str = "why") -> None:
    st.caption(f"🤖 {llm_status()}")
    suggestions = suggestions or []
    cols = st.columns(max(1, len(suggestions)))
    for col, q in zip(cols, suggestions):
        if col.button(q, key=f"{key}_s_{q}"):
            st.session_state[f"{key}_q"] = q
    question = st.text_input(t("why.your_question"), key=f"{key}_q",
                             placeholder=suggestions[0] if suggestions else t("why.placeholder"))
    if st.button(t("why.ask"), type="primary", disabled=not question, key=f"{key}_ask"):
        with st.spinner(t("why.investigating")):
            st.session_state[f"{key}_answer"] = WhyAgent(run_id, journal=journal).ask(question)

    a = st.session_state.get(f"{key}_answer")
    if a is None or a.run_id != run_id:
        return
    st.caption(source_badge(a.source))
    (st.success if a.source.startswith("llm:") else st.warning)(a.answer)
    entries = {e.entry_id: e for e in read_events(journal, run_id=run_id)}
    for i in a.citations:
        e = entries.get(i)
        if e is not None:
            with st.expander(t("why.proof", i=i, what=f"{e.agent}.{e.step} · {e.decision}")):
                st.write(t("audit.rule", rule=e.rule_version or "-"))
                st.json(e.evidence, expanded=False)
    if a.tool_calls or a.rejected:
        with st.expander(t("why.how")):
            st.write(t("why.tools", tools=" → ".join(f"`{c['tool']}`" for c in a.tool_calls) or t("common.none")))
            for r in a.rejected:
                st.write(t("why.rejected", reason=r))
