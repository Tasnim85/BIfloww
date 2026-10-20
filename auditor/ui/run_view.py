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
from auditor.ui.data import base_run, journal_for, read, runs_with
from contracts.common import Period, load
from contracts.pipeline import context_for, output_path
from contracts.semantic import AnalysisRequest, KpiCatalog, load_yaml
from contracts.warehouse import WarehouseManifest


def _placeholder_dashboard(run_id: str, request: AnalysisRequest, periods: tuple[Period, Period]) -> None:
    """Stand-in for Samar's dashboard: the requested KPI by its first dimension, from the catalog.
    Nothing here is specific to a dataset: tables, columns, filters and unit come from the
    catalog, the manifest and the request."""
    data_run = base_run(run_id)
    warehouse = output_path(data_run, "etl", "warehouse")
    manifest_path = output_path(data_run, "etl", "manifest")
    if not warehouse.exists() or not manifest_path.exists():
        st.info("Pas d'entrepôt pour ce run : le dashboard ne peut pas être dessiné.")
        return
    catalog = load_yaml(KpiCatalog, context_for("comparisons", data_run).inputs["catalog"])
    kpi = catalog.kpi(request.metric)
    manifest = load(WarehouseManifest, manifest_path)
    where = " AND ".join(f"({f})" for f in kpi.filters + request.filters) or "TRUE"

    dim = next((d for d in catalog.dimensions if d.name in request.dimensions), None)
    if dim is None:
        group, join = "'total'", ""
    elif dim.table == kpi.table:
        group, join = f"f.{dim.column}", ""
    else:
        keys = next(t.primary_key for t in manifest.tables if t.name == dim.table)
        group, join = f"d.{dim.column}", f"JOIN {dim.table} d USING ({', '.join(keys)})"
    sql = (f"SELECT {group} AS label, {kpi.expression} AS value FROM {kpi.table} f {join} "
           f"WHERE {where} AND f.{kpi.date_column} BETWEEN ? AND ? GROUP BY 1")
    with duckdb.connect(str(warehouse), read_only=True) as con:
        frames = {name: con.execute(sql, [p.start, p.end]).df().set_index("label")["value"]
                  for name, p in zip(("current", "previous"), periods)}
    df = pd.DataFrame(frames).fillna(0).sort_values("current", ascending=False).head(10)

    c1, c2, c3 = st.columns(3)
    cur, prev = df["current"].sum(), df["previous"].sum()
    c1.metric(f"{kpi.name} · {periods[0].start} → {periods[0].end}", f"{cur:,.0f} {kpi.unit}",
              f"{(cur / prev - 1):+.1%}" if prev else None)
    c2.metric(f"Comparé à {periods[1].start} → {periods[1].end}", f"{prev:,.0f} {kpi.unit}")
    c3.metric("KPI", kpi.ref)
    fig, ax = plt.subplots(figsize=(9, 3))
    x = range(len(df))
    ax.bar([i - 0.2 for i in x], df["previous"], width=0.4, label="période comparée", color="#9ecae1")
    ax.bar([i + 0.2 for i in x], df["current"], width=0.4, label="période étudiée", color="#1f77b4")
    ax.set_xticks(list(x), [str(v) for v in df.index])
    ax.set_ylabel(kpi.unit)
    ax.legend(fontsize=8)
    ax.set_title(f"{kpi.name} par {dim.name if dim else 'total'} (10 premiers)")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption("Graphique PROVISOIRE : dans l'application de l'équipe, ce sont les graphiques de Samar, "
               "dessinés pour les périodes renvoyées par le bandeau BO4-12.")


def render() -> None:
    runs = [r for r in runs_with("request", "request") if output_path(r, "comparisons", "report").exists()]
    if not runs:
        st.error("Aucun run avec une question. Lance `python -m auditor.dev.seed_demo_journal`.")
        return
    run_id = st.sidebar.selectbox("Run", runs, key="rv_run")
    journal = journal_for(run_id)
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
        _placeholder_dashboard(run_id, request, periods)

    st.divider()
    with st.expander("🛡️ Audit de ce run", expanded=False):
        audit_panel(run_id, journal)
    st.subheader("💬 Une question sur ces chiffres ?")
    why_box(run_id, journal, suggestions=["Pourquoi la comparaison a-t-elle été bloquée ?",
                                          f"D'où vient le chiffre « {request.metric} » ?"], key=f"rv_why_{run_id}")
