"""Page "Analysis result": one run, with all of Rabeb's blocks, and a button to run the Analyst.
The chart is a simple view of result.parquet; in the team app Samar's dashboard draws it."""
import matplotlib.pyplot as plt
import streamlit as st

from analysis.analyst import run as run_analyst
from analysis.ui.components import insights_box, kpi_header, sql_box, validation_panel
from analysis.ui.data import llm_status, read, result_table, runs_with
from analysis.ui.texts import t
from contracts.pipeline import context_for


def _chart(run_id: str) -> None:
    r, df = read(run_id, "analysis.result"), result_table(run_id)
    if r is None or df is None or df.empty or not r.request.dimensions:
        return
    dim = r.request.dimensions[0]
    table = df.pivot_table(index=dim, columns="period", values="value", aggfunc="sum").fillna(0)
    fig, ax = plt.subplots(figsize=(9, 3))
    x = range(len(table))
    if "previous" in table:
        ax.bar([i - 0.2 for i in x], table["previous"], width=0.4, label=t("run.prev"), color="#9ecae1")
    ax.bar([i + 0.2 for i in x], table.get("current", 0), width=0.4, label=t("run.current"), color="#1f77b4")
    ax.set_xticks(list(x), [str(v) for v in table.index])
    ax.set_ylabel(r.unit)
    ax.set_title(t("run.chart", kpi=r.kpi.split("@")[0], dim=dim))
    ax.legend(fontsize=8)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def render() -> None:
    st.title(t("run.title"))
    st.caption(t("run.caption"))
    runs = runs_with("request", "request")
    if not runs:
        st.info(t("common.no_run"))
        st.code("python -m analysis.dev_warehouse", language="bash")
        return
    run_id = st.selectbox(t("common.run"), runs, key="an_run")

    with st.form("an_launch"):
        use_llm = st.checkbox(t("run.use_llm"), value=True)
        st.caption(t("common.llm", status=llm_status()))
        if st.form_submit_button(t("run.launch"), type="primary"):
            with st.spinner(t("run.running")):
                out = run_analyst(context_for("analysis", run_id, params={"llm": use_llm}))
            st.toast(t("run.done", status=out.status.value, message=out.message))

    r = read(run_id, "analysis.result")
    if r is None:
        st.info(t("run.no_result"))
        return
    st.markdown("#### " + t("run.question", q=r.request.question))
    kpi_header(run_id)
    _chart(run_id)
    insights_box(run_id)
    validation_panel(run_id)
    sql_box(run_id)
