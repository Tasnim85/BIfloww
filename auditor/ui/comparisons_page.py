"""BO4-12 page: is this comparison honest? Display + user decision. No business logic."""
from datetime import date

import matplotlib.pyplot as plt
import streamlit as st

from auditor.ui.data import DEMO_JOURNAL, UI_JOURNAL, read, source_badge
from comparisons.checker import record_decision, run as run_checker
from contracts.agent import RunContext
from contracts.common import Period, load, save
from contracts.comparisons import CheckStatus, ComparisonReport
from contracts.pipeline import RUNS_ROOT, context_for, output_path
from contracts.semantic import AnalysisRequest

ICON = {CheckStatus.OK: "✅", CheckStatus.WARNING: "⚠️", CheckStatus.BLOCKING: "⛔"}
CUSTOM_RUN = "ui_custom"


def _run_custom(cur: tuple[date, date], prev: tuple[date, date], use_llm: bool) -> None:
    """Run the real BO4-12 agent on a request typed in the UI (data of run_001)."""
    req = AnalysisRequest(question="Comparaison saisie dans l'interface", metric="Revenue",
                          dimensions=["customer_state"],
                          period=Period(start=cur[0].isoformat(), end=cur[1].isoformat()),
                          compare_to=Period(start=prev[0].isoformat(), end=prev[1].isoformat()))
    inputs = dict(context_for("comparisons", "run_001").inputs)
    inputs["request"] = save(req, output_path(CUSTOM_RUN, "request", "request"))
    inputs["result"] = output_path(CUSTOM_RUN, "analysis", "result")         # none: values recomputed
    ctx = RunContext(run_id=CUSTOM_RUN, agent="comparisons", inputs=inputs,
                     output_dir=RUNS_ROOT / CUSTOM_RUN / "comparisons",
                     params={"llm": use_llm}, journal=UI_JOURNAL)
    run_checker(ctx)


def _coverage_chart(run_id: str, report: ComparisonReport, request: AnalysisRequest):
    cov = read(run_id if run_id != CUSTOM_RUN else "run_001", "profiling.coverage")
    check = next((c for c in report.checks if c.kind.value == "coverage"), None)
    if cov is None or check is None:
        return None
    lo = min(request.period.start, request.compare_to.start)
    hi = max(request.period.end, request.compare_to.end)
    days = [d for d in cov.tables[0].days if lo <= d.date <= hi]
    bad = set(check.evidence.get("current", {}).get("incomplete_days", {})) | \
        set(check.evidence.get("previous", {}).get("incomplete_days", {}))
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.bar(range(len(days)), [d.rows for d in days],
           color=["#d62728" if d.date in bad else "#1f77b4" for d in days])
    thr = check.evidence.get("current", {}).get("threshold_rows")
    if thr:
        ax.axhline(thr, color="#d62728", linestyle="--", linewidth=0.8, label=f"seuil ({thr:.0f}/jour)")
        ax.legend(loc="upper left", fontsize=8)
    step = max(1, len(days) // 12)
    ax.set_xticks(range(0, len(days), step), [days[i].date[5:] for i in range(0, len(days), step)], fontsize=8)
    ax.set_ylabel("commandes / jour")
    fig.tight_layout()
    return fig


def render() -> None:
    st.title("Comparaisons trompeuses (BO4-12)")
    st.caption("Profil de couverture (DQ) + catalogue (SEM) → 5 contrôles → correction justifiée → "
               "décision de l'utilisateur → journal")

    with st.expander("Essayer une autre comparaison", expanded=False):
        with st.form("custom"):
            c1, c2 = st.columns(2)
            cur = c1.date_input("Période étudiée", (date(2018, 2, 1), date(2018, 2, 28)))
            prev = c2.date_input("Comparée à", (date(2018, 1, 1), date(2018, 1, 31)))
            use_llm = st.checkbox("Résumé rédigé par le LLM (vérifié)", value=False)
            go = st.form_submit_button("Lancer l'agent BO4-12", type="primary")
        st.caption("Idées : février vs janvier 2018 (échelle), 1-7 mai vs avril 2018 (échelle), "
                   "septembre vs août 2018 (couverture), juin vs mai 2018 (valide).")
        if go and len(cur) == 2 and len(prev) == 2:
            with st.spinner("L'agent vérifie la comparaison..."):
                _run_custom(cur, prev, use_llm)
            st.session_state["cmp_run"] = CUSTOM_RUN

    choices = [r for r in ("run_001", CUSTOM_RUN) if output_path(r, "comparisons", "report").exists()]
    if not choices:
        st.error("Aucun rapport de comparaison. Lance `python -m auditor.dev.seed_demo_journal`.")
        return
    default = st.session_state.get("cmp_run", choices[0])
    run_id = st.radio("Rapport affiché", choices, index=choices.index(default) if default in choices else 0,
                      horizontal=True, format_func=lambda r: "Scénario août/juillet (run_001)"
                      if r == "run_001" else "Ma comparaison")
    report = load(ComparisonReport, output_path(run_id, "comparisons", "report"))
    request = load(AnalysisRequest, output_path(run_id, "request", "request"))
    journal = DEMO_JOURNAL if run_id == "run_001" else UI_JOURNAL

    st.subheader("La question")
    st.write(f"**{request.metric}** du {request.period.start} au {request.period.end}, "
             f"comparé au {request.compare_to.start} – {request.compare_to.end}")

    if not report.has_comparison:
        st.info(report.summary)
        return

    blocking = any(c.status == CheckStatus.BLOCKING for c in report.checks)
    (st.error if blocking else st.success)(
        "Comparaison trompeuse telle que demandée" if blocking else "Comparaison valide")

    st.subheader("Les 5 contrôles")
    for c in report.checks:
        with st.expander(f"{ICON[c.status]} {c.kind.value} — {c.status.value}", expanded=c.status != CheckStatus.OK):
            st.write(c.message)
            st.json(c.evidence, expanded=False)

    fig = _coverage_chart(run_id, report, request)
    if fig is not None:
        st.subheader("Couverture : commandes par jour")
        st.pyplot(fig)
        plt.close(fig)
        st.caption("Rouge = jours incomplets en bord de données (règle versionnée "
                   f"{report.rules_version}).")

    fixes = ([report.proposed_fix] if report.proposed_fix else []) + report.alternatives
    if fixes:
        st.subheader("Corrections proposées")
        cols = st.columns(len(fixes))
        for col, f, i in zip(cols, fixes, range(len(fixes))):
            with col:
                st.markdown(f"**{'Recommandée' if i == 0 else 'Alternative'} · {f.method.value}**")
                st.metric(f"{f.period.start} → {f.period.end}", f"{f.value_current:,.2f} {f.unit}",
                          f"{f.change_pct:+.1%}" if f.change_pct is not None else None)
                st.caption(f"contre {f.value_previous:,.2f} {f.unit} ({f.compare_to.start} → {f.compare_to.end})")
                st.write(f.justification)

    st.subheader("Résumé pour l'utilisateur")
    st.caption(source_badge(report.summary_source))
    st.info(report.summary)

    st.subheader("Décision de l'utilisateur")
    st.write(f"État : **{report.user_decision.value}**"
             + (f" ({report.chosen_fix.value})" if report.chosen_fix else ""))
    if fixes:
        cols = st.columns(len(fixes) + 1)
        for col, f in zip(cols, fixes):
            if col.button(f"Accepter {f.method.value}", key=f"acc_{f.method.value}"):
                record_decision(run_id, "accepted", f.method.value, journal=journal)
                st.rerun()
        if cols[-1].button("Refuser"):
            record_decision(run_id, "rejected", journal=journal)
            st.rerun()
        st.caption("Chaque décision est inscrite dans le journal. Rien n'est appliqué sans elle.")
