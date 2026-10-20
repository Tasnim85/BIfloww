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

from auditor.ui.data import llm_status, read, source_badge
from auditor.why import WhyAgent
from comparisons.checker import record_decision
from contracts.audit import read_events, verify_journal
from contracts.common import Period
from contracts.comparisons import CheckStatus, UserDecision

ROUTINE = {"OK", "PASSED", "computed in SQL", "answered (template)"}


# ---- 1. Header badge --------------------------------------------------------------
def trust_badge(run_id: str, journal: Path, key: str = "badge") -> None:
    integrity = verify_journal(journal)
    cmp = read(run_id, "comparisons.report")
    drift = read(run_id, "auditor.drift")
    expl = read(run_id, "auditor.explanations")

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"{'✅' if integrity.ok else '⛔'} **Journal** "
                f"{'intact' if integrity.ok else 'FALSIFIÉ'} ({integrity.entries_checked} décisions)")
    if cmp is None or not cmp.has_comparison:
        c2.markdown("➖ **Comparaison** : aucune")
    else:
        blocking = any(c.status == CheckStatus.BLOCKING for c in cmp.checks)
        state = {UserDecision.ACCEPTED: "ajustée", UserDecision.REJECTED: "telle que demandée",
                 UserDecision.PENDING: "à confirmer"}[cmp.user_decision]
        c2.markdown(f"{'⚠️' if blocking else '✅'} **Comparaison** "
                    f"{state if blocking else 'valide'}")
    if drift is None or drift.status == "not_available":
        c3.markdown("➖ **Drift** : pas de référence")
    else:
        c3.markdown(f"{'✅' if drift.status == 'stable' else '⚠️'} **Drift** : {drift.status}")
    n = sum(e.is_anomaly for e in expl.explanations) if expl else 0
    c4.markdown(f"🔍 **{n} anomalies** expliquées" if expl else "🔍 **Anomalies** : non expliquées")


# ---- 2. BO4-12 banner -------------------------------------------------------------
def comparison_banner(run_id: str, journal: Path, key: str = "banner") -> tuple[Period, Period] | None:
    """Draws the BO4-12 verdict and the user's choice. Returns the (period, compare_to) the
    dashboard must use, or None while the user has not decided on a blocked comparison."""
    report = read(run_id, "comparisons.report")
    request = read(run_id, "request.request")
    if request is None or request.compare_to is None or report is None or not report.has_comparison:
        return (request.period, request.compare_to) if request else None

    fixes = ([report.proposed_fix] if report.proposed_fix else []) + report.alternatives
    asked = (request.period, request.compare_to)
    blocking = any(c.status == CheckStatus.BLOCKING for c in report.checks)

    if report.user_decision == UserDecision.ACCEPTED and report.chosen_fix:
        f = next(x for x in fixes if x.method == report.chosen_fix)
        st.success(f"Comparaison ajustée ({f.method.value}) : {f.description} "
                   f"Résultat {f.value_current:,.2f} contre {f.value_previous:,.2f} {f.unit} "
                   f"({f.change_pct:+.1%}).")
        if st.button("Revoir ce choix", key=f"{key}_undo"):
            record_decision(run_id, "pending", journal=journal)
            st.rerun()
        return (f.period, f.compare_to)
    if report.user_decision == UserDecision.REJECTED:
        if blocking:
            st.warning("Comparaison affichée telle que demandée, malgré l'avertissement : "
                       + next(c.message for c in report.checks if c.status == CheckStatus.BLOCKING))
        if st.button("Revoir ce choix", key=f"{key}_undo"):
            record_decision(run_id, "pending", journal=journal)
            st.rerun()
        return asked
    if not blocking:
        warnings = [c.message for c in report.checks if c.status == CheckStatus.WARNING]
        if warnings:
            st.info("À noter : " + " ".join(warnings))
        if not fixes:
            return asked

    (st.error if blocking else st.info)(
        ("⛔ Cette comparaison est trompeuse telle que demandée. " if blocking else "Un ajustement est possible. ")
        + f"({source_badge(report.summary_source)})")
    st.write(report.summary)
    cols = st.columns(len(fixes) + 1)
    for col, f, i in zip(cols, fixes, range(len(fixes))):
        label = f"{'✔ ' if i == 0 else ''}{f.description.split(':')[0]} ({f.change_pct:+.1%})"
        if col.button(label, key=f"{key}_{f.method.value}", type="primary" if i == 0 else "secondary"):
            record_decision(run_id, "accepted", f.method.value, journal=journal)
            st.rerun()
    if cols[-1].button("Garder la comparaison demandée", key=f"{key}_reject"):
        record_decision(run_id, "rejected", journal=journal)
        st.rerun()
    st.caption("Le pipeline attend votre choix. Il est inscrit dans le journal d'audit.")
    return None if blocking else asked


# ---- 3. Audit panel -----------------------------------------------------------------
def audit_panel(run_id: str, journal: Path, key: str = "audit") -> None:
    events = [e for e in read_events(journal, run_id=run_id)
              if not e.step.startswith("llm:") and e.step != "why_answer"]
    tabs = st.tabs(["Décisions", "Anomalies", "Intégrité", "Drift"])

    with tabs[0]:
        if not events:
            st.info("Aucune décision journalisée pour ce run.")
        notable_only = st.checkbox("Seulement les décisions notables", value=True, key=f"{key}_notable")
        for agent in dict.fromkeys(e.agent for e in events):
            rows = [e for e in events if e.agent == agent and (not notable_only or e.decision not in ROUTINE)]
            if not rows:
                continue
            st.markdown(f"**{agent}**")
            for e in rows:
                with st.expander(f"#{e.entry_id} · {e.step} · {e.decision}"):
                    st.write(f"Règle / version : `{e.rule_version or '-'}`")
                    st.json(e.evidence, expanded=False)

    with tabs[1]:
        expl = read(run_id, "auditor.explanations")
        if expl is None:
            st.info("Pas d'explications SHAP pour ce run.")
        else:
            for e in [x for x in expl.explanations if x.is_anomaly][:5]:
                with st.expander(f"{e.row_key} · score {e.anomaly_score:.3f}"):
                    st.write(e.narrative)
            st.caption("Les 5 plus fortes. Toutes sont dans la page « Expliquer une anomalie ».")

    with tabs[2]:
        rep = verify_journal(journal)
        (st.success if rep.ok else st.error)(f"{rep.problem} ({rep.entries_checked} entrées vérifiées)")

    with tabs[3]:
        drift = read(run_id, "auditor.drift")
        if drift is None:
            st.info("Pas de rapport de drift pour ce run.")
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
    question = st.text_input("Votre question", key=f"{key}_q",
                             placeholder=suggestions[0] if suggestions else "Pourquoi … ?")
    if st.button("Demander", type="primary", disabled=not question, key=f"{key}_ask"):
        with st.spinner("L'agent enquête dans le journal..."):
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
            with st.expander(f"Preuve #{i} · {e.agent}.{e.step} · {e.decision}"):
                st.write(f"Règle / version : `{e.rule_version or '-'}`")
                st.json(e.evidence, expanded=False)
    if a.tool_calls or a.rejected:
        with st.expander("Comment l'agent a travaillé"):
            st.write("Outils : " + (" → ".join(f"`{c['tool']}`" for c in a.tool_calls) or "aucun"))
            for r in a.rejected:
                st.write(f"🔁 Brouillon refusé : {r}")
