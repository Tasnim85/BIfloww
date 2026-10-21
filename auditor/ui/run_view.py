"""MOCK-UP of the pipeline's result screen for one run, showing where Tasnim's blocks go.

The middle part (charts) is a PLACEHOLDER for Samar's dashboard (step 6): a simple
revenue-by-state chart, drawn for the periods the BO4-12 banner returns, so the
effect of the user's choice is visible. In the team app, Samar's charts replace it.
"""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from auditor.ui.components import audit_panel, comparison_banner, trust_badge, why_box
from auditor.ui.data import base_run, journal_for, read, runs_with, t, ui_lang
from comparisons.values import kpi_by_dimension
from contracts.common import Period, load
from contracts.i18n import fmt
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
        st.info(t("run.no_warehouse"))
        return
    catalog = load_yaml(KpiCatalog, context_for("comparisons", data_run).inputs["catalog"])
    kpi = catalog.kpi(request.metric)
    b = kpi_by_dimension(warehouse, load(WarehouseManifest, manifest_path), catalog, request,
                         *periods, limit=10)                # the same query as the API
    dim = b.dimension
    df = pd.DataFrame([r.model_dump() for r in b.rows]).set_index("label").fillna(0) if b.rows else \
        pd.DataFrame({"current": [], "previous": []})

    c1, c2, c3 = st.columns(3)
    cur, prev = b.total_current, b.total_previous or 0
    lang = ui_lang()
    c1.metric(f"{kpi.name} · {periods[0].start} → {periods[0].end}", f"{fmt(cur, 'num0', lang)} {kpi.unit}",
              fmt(cur / prev - 1, "spct", lang) if prev else None)
    if periods[1] is not None:
        c2.metric(t("run.compared_to", start=periods[1].start, end=periods[1].end),
                  f"{fmt(prev, 'num0', lang)} {kpi.unit}")
    c3.metric("KPI", kpi.ref)
    fig, ax = plt.subplots(figsize=(9, 3))
    x = range(len(df))
    ax.bar([i - 0.2 for i in x], df["previous"], width=0.4, label=t("run.previous"), color="#9ecae1")
    ax.bar([i + 0.2 for i in x], df["current"], width=0.4, label=t("run.studied"), color="#1f77b4")
    ax.set_xticks(list(x), [str(v) for v in df.index])
    ax.set_ylabel(kpi.unit)
    ax.legend(fontsize=8)
    ax.set_title(t("run.chart_title", kpi=kpi.name, dim=dim or t("run.total")))
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption(t("run.placeholder"))


def render() -> None:
    runs = [r for r in runs_with("request", "request") if output_path(r, "comparisons", "report").exists()]
    if not runs:
        st.error(t("run.no_runs"))
        return
    run_id = st.sidebar.selectbox(t("common.run"), runs, key="rv_run")
    journal = journal_for(run_id)
    request = read(run_id, "request.request")

    st.title(t("run.title"))
    st.caption(t("run.caption"))
    st.markdown("#### " + t("run.question", q=request.question))
    trust_badge(run_id, journal)
    st.divider()

    periods = comparison_banner(run_id, journal)
    if periods is None:
        st.info(t("run.wait"))
    elif request.compare_to is not None:
        _placeholder_dashboard(run_id, request, periods)

    st.divider()
    with st.expander(t("run.audit"), expanded=False):
        audit_panel(run_id, journal)
    st.subheader(t("run.ask_header"))
    why_box(run_id, journal, suggestions=[t("why.q_blocked"), t("why.q_where", metric=request.metric)],
            key=f"rv_why_{run_id}_{ui_lang()}")
