"""Page "KPI proposer": a draft catalog + glossary for the warehouse of any run.
Nothing is written into kpi/catalog.yaml: the drafts are downloaded and reviewed by a human."""
import pandas as pd
import streamlit as st
import yaml

from analysis.kpi_proposer import HEADER, propose
from analysis.ui.data import catalog, glossary, llm_status, read, runs_with
from analysis.ui.texts import t
from contracts.pipeline import output_path


def _yaml(obj, source: str, target: str) -> str:
    return HEADER.format(source=source, target=target) + yaml.safe_dump(
        obj.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def render() -> None:
    st.title(t("prop.title"))
    st.caption(t("prop.caption"))
    runs = runs_with("etl", "warehouse")
    if not runs:
        st.info(t("common.no_run"))
        st.code("python -m analysis.dev_warehouse", language="bash")
        return
    with st.form("prop_form"):
        run_id = st.selectbox(t("prop.data_of"), runs, key="prop_run")
        use_llm = st.checkbox(t("prop.use_llm"), value=True)
        st.caption(t("common.llm", status=llm_status()))
        go = st.form_submit_button(t("prop.go"), type="primary")
    if go:
        with st.spinner(t("prop.running")):
            st.session_state["prop"] = (run_id, *propose(read(run_id, "etl.manifest"),
                                                          output_path(run_id, "etl", "warehouse"),
                                                          use_llm=use_llm, approved=catalog(run_id),
                                                          approved_glossary=glossary()))
    if "prop" not in st.session_state:
        return
    run_id, cat, gloss, source = st.session_state["prop"]
    st.success(t("prop.result", source=source, k=len(cat.kpis), d=len(cat.dimensions)))
    approved = {k.ref for k in catalog(run_id).kpis}
    rows = [{"KPI": k.ref, "formula": k.expression, "table": k.table, "unit": k.unit,
             "dimensions": ", ".join(k.allowed_dimensions)} for k in cat.kpis]
    st.markdown(f"**{t('prop.approved')}**")
    st.dataframe(pd.DataFrame([r for r in rows if r["KPI"] in approved]), hide_index=True)
    st.markdown(f"**{t('prop.new')}**")
    st.dataframe(pd.DataFrame([r for r in rows if r["KPI"] not in approved]), hide_index=True)
    st.warning(t("prop.review"))
    c1, c2 = st.columns(2)
    c1.download_button(t("prop.dl_catalog"), _yaml(cat, source, "kpi/catalog.yaml"),
                       file_name="kpi_catalog_proposal.yaml")
    c2.download_button(t("prop.dl_glossary"), _yaml(gloss, source, "semantic/glossary.yaml"),
                       file_name="glossary_proposal.yaml")
