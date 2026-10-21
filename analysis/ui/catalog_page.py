"""Page "KPI catalog": the approved KPIs, dimensions and glossary, and a KPI tried live on a
warehouse with the Analyst's own compiler and BO3-03 checks (read-only: nothing is written)."""
import duckdb
import pandas as pd
import streamlit as st

from analysis.sql_compiler import CompileError, compile_query
from analysis.ui.data import catalog, glossary, read, runs_with
from analysis.ui.texts import t
from analysis.validations import run_checks
from contracts.common import Period
from contracts.pipeline import output_path
from contracts.semantic import AnalysisRequest


def _try_kpi(cat) -> None:
    runs = runs_with("etl", "warehouse")
    if not runs:
        st.info(t("common.no_run"))
        st.code("python -m analysis.dev_warehouse", language="bash")
        return
    c1, c2, c3 = st.columns(3)
    run_id = c1.selectbox(t("common.run"), runs, key="cat_run")
    metric = c2.selectbox(t("cat.kpi"), [k.name for k in cat.kpis], key="cat_kpi")
    dim = c3.selectbox(t("cat.dim"), [None] + cat.kpi(metric).allowed_dimensions, key="cat_dim",
                       format_func=lambda d: t("cat.none") if d is None else d)
    manifest = read(run_id, "etl.manifest")
    table = next(x for x in manifest.tables if x.name == cat.kpi(metric).table)
    d1, d2 = st.columns(2)
    start = d1.text_input(t("cat.start"), table.date_min or "", key="cat_start")
    end = d2.text_input(t("cat.end"), table.date_max or "", key="cat_end")
    if not st.button(t("cat.go"), type="primary", key="cat_go"):
        return
    request = AnalysisRequest(question="catalog page", metric=metric, dimensions=[dim] if dim else [],
                              period=Period(start=start, end=end))
    try:
        q = compile_query(request, cat, manifest)
    except CompileError as e:
        st.error(t("cat.error", e=e))
        return
    con = duckdb.connect(str(output_path(run_id, "etl", "warehouse")), read_only=True)
    try:
        df = con.execute(q.sql).df()
        totals = df.groupby("period")["value"].sum().to_dict()
        checks = run_checks(con, q, manifest, read(run_id, "etl.receipts"), totals)
    finally:
        con.close()
    st.subheader(t("cat.result"))
    st.dataframe(df.drop(columns="period"), hide_index=True)
    for c in checks:
        st.write(f"{'✅' if c.passed else '⛔'} {t('checks.name.' + c.name)}: {c.detail}")
    st.code(q.sql, language="sql")


def render() -> None:
    st.title(t("cat.title"))
    st.caption(t("cat.caption") + f" · v{catalog().version}")
    cat = catalog()
    st.subheader(t("cat.kpis", n=len(cat.kpis)))
    st.dataframe(pd.DataFrame([{"KPI": k.ref, "formula": k.expression, "table": k.table, "unit": k.unit,
                                "filters": " AND ".join(k.filters), "population": k.population,
                                "dimensions": ", ".join(k.allowed_dimensions)} for k in cat.kpis]),
                 hide_index=True)
    st.subheader(t("cat.dims", n=len(cat.dimensions)))
    st.dataframe(pd.DataFrame([{"name": d.name, "column": f"{d.table}.{d.column}", "description": d.description}
                               for d in cat.dimensions]), hide_index=True)
    g = glossary()
    if g is not None:
        st.subheader(t("cat.glossary"))
        st.dataframe(pd.DataFrame([{"term": x.term, "kind": x.kind, "synonyms": ", ".join(x.synonyms)}
                                   for x in g.terms]), hide_index=True)
    st.divider()
    st.subheader(t("cat.try"))
    _try_kpi(cat)
