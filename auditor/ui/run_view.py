"""MOCK-UP of the pipeline's result screen for one run, showing where Tasnim's blocks go.

The middle part (charts) is a PLACEHOLDER for Samar's dashboard (step 6): a simple
revenue-by-state chart, drawn for the periods the BO4-12 banner returns, so the
effect of the user's choice is visible. In the team app, Samar's charts replace it.
"""
import duckdb
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from auditor.ui.components import audit_panel, comparison_banner, trust_badge, why_box
from auditor.ui.data import DEMO_JOURNAL, UI_JOURNAL, read, runs_with
from contracts.common import Period
from contracts.pipeline import REPO_ROOT, output_path
from contracts.semantic import KpiCatalog, load_yaml

JOURNAL_OF = {"run_001": DEMO_JOURNAL, "ui_custom": UI_JOURNAL}


def _placeholder_dashboard(run_id: str, metric: str, periods: tuple[Period, Period]) -> None:
    """Stand-in for Samar's dashboard: KPI by customer state, computed from the catalog."""
    warehouse = output_path("run_001" if run_id == "ui_custom" else run_id, "etl", "warehouse")
    if not warehouse.exists():
        st.info("Pas d'entrepôt pour ce run : le dashboard ne peut pas être dessiné.")
        return
    kpi = load_yaml(KpiCatalog, REPO_ROOT / "kpi" / "catalog.yaml").kpi(metric)
    where = " AND ".join(f"({f})" for f in kpi.filters) or "TRUE"
    sql = (f"SELECT c.customer_state AS state, {kpi.expression} AS value FROM {kpi.table} f "
           f"JOIN dim_customer c USING (customer_id) WHERE {where} "
           f"AND f.{kpi.date_column} BETWEEN ? AND ? GROUP BY 1")
    with duckdb.connect(str(warehouse), read_only=True) as con:
        frames = {label: con.execute(sql, [p.start, p.end]).df().set_index("state")["value"]
                  for label, p in zip(("current", "previous"), periods)}
    df = pd.DataFrame(frames).fillna(0).sort_values("current", ascending=False).head(10)
    c1, c2, c3 = st.columns(3)
    cur, prev = df["current"].sum(), df["previous"].sum()
    c1.metric(f"{metric} · {periods[0].start} → {periods[0].end}", f"{cur:,.0f} {kpi.unit}",
              f"{(cur / prev - 1):+.1%}" if prev else None)
    c2.metric(f"Comparé à {periods[1].start} → {periods[1].end}", f"{prev:,.0f} {kpi.unit}")
    c3.metric("KPI", kpi.ref)
    fig, ax = plt.subplots(figsize=(9, 3))
    x = range(len(df))
    ax.bar([i - 0.2 for i in x], df["previous"], width=0.4, label="période comparée", color="#9ecae1")
    ax.bar([i + 0.2 for i in x], df["current"], width=0.4, label="période étudiée", color="#1f77b4")
    ax.set_xticks(list(x), df.index)
    ax.set_ylabel(kpi.unit)
    ax.legend(fontsize=8)
    ax.set_title(f"{metric} par État (10 premiers)")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption("Graphique PROVISOIRE : dans l'application de l'équipe, ce sont les graphiques de Samar, "
               "dessinés pour les périodes renvoyées par le bandeau BO4-12.")


def render() -> None:
    runs = [r for r in runs_with("request", "request") if r in JOURNAL_OF]
    if not runs:
        st.error("Aucun run avec une question. Lance `python -m auditor.dev.seed_demo_journal`.")
        return
    run_id = st.sidebar.selectbox("Run", runs, key="rv_run")
    journal = JOURNAL_OF[run_id]
    request = read(run_id, "request.request")

    st.title("Résultat d'un run")
    st.caption("Maquette de l'écran final du pipeline : en bleu, les blocs de la partie Auditor / BO4-12.")
    st.markdown(f"#### « {request.question} »")
    trust_badge(run_id, journal)
    st.divider()

    periods = comparison_banner(run_id, journal)
    if periods is None:
        st.info("⏸️ Le dashboard sera affiché après votre choix ci-dessus.")
    elif request.compare_to is not None:
        _placeholder_dashboard(run_id, request.metric, periods)

    st.divider()
    with st.expander("🛡️ Audit de ce run", expanded=False):
        audit_panel(run_id, journal)
    st.subheader("💬 Une question sur ces chiffres ?")
    why_box(run_id, journal, suggestions=["Pourquoi la comparaison a-t-elle été bloquée ?",
                                          "D'où vient le chiffre d'affaires ?"], key="rv_why")
