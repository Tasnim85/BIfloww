"""The "why?" agent page: the why_box component on any run of any journal."""
import streamlit as st

from auditor.ui.components import why_box
from auditor.ui.data import pick_journal, runs_in, t, ui_lang

SUGGESTIONS = {"run_001": ["q_aug_jul", "q_revenue", "q_anomaly"],   # keys of i18n "ui.why.*"
               "other": ["q_flagged", "q_inputs"]}


def render() -> None:
    st.title(t("whyp.title"))
    st.caption(t("whyp.caption"))
    c1, c2 = st.columns(2)
    with c1:
        journal = pick_journal(key="why_journal", prefer="demo")
    if journal is None:
        return
    with c2:
        run_id = st.selectbox(t("common.run"), runs_in(journal), key="why_run")
    keys = SUGGESTIONS["run_001"] if run_id == "run_001" else SUGGESTIONS["other"]
    why_box(run_id, journal, [t(f"why.{k}") for k in keys], key=f"whypage_{run_id}_{ui_lang()}")
