"""SHAP page: why was this row flagged? Display only."""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from auditor.ui.data import read, runs_with, t
from auditor.xai.explain import build_report
from auditor.xai.narrator import label
from contracts.common import save
from contracts.pipeline import context_for, output_path


def render() -> None:
    st.title(t("shap.title"))
    st.caption(t("shap.caption"))

    runs = runs_with("profiling", "anomalies")
    if not runs:
        st.error(t("shap.no_profiling"))
        return
    run_id = st.selectbox(t("common.run"), runs, index=runs.index("run_001") if "run_001" in runs else 0)

    report = read(run_id, "auditor.explanations")
    if report is None:
        st.info(t("shap.not_computed"))
        if st.button(t("shap.compute"), type="primary"):
            ctx = context_for("auditor", run_id)
            with st.spinner(t("shap.computing")):
                save(build_report(ctx.inputs["anomalies"], ctx.inputs["model"], ctx.inputs["scores"]),
                     output_path(run_id, "auditor", "explanations"))
            st.rerun()
        return

    anomalies = [e for e in report.explanations if e.is_anomaly]
    normals = [e for e in report.explanations if not e.is_anomaly]
    c1, c2, c3 = st.columns(3)
    c1.metric(t("shap.n_anomalies"), len(anomalies))
    c2.metric(t("shap.n_normals"), len(normals))
    c3.metric(t("shap.model"), report.model_version)
    st.success(t("shap.exact"))

    scope = st.radio(t("shap.which"), ["anomalies", "normals"], horizontal=True,
                     format_func=lambda k: t(f"shap.opt_{k}"))
    rows = anomalies if scope == "anomalies" else normals
    if not rows:
        st.info(t("shap.none"))
        return
    e = st.selectbox(t("shap.row"), rows[:200], format_func=lambda x: f"{x.row_key} · score {x.anomaly_score:.3f}")

    (st.error if e.is_anomaly else st.success)(t(
        "shap.row_state", key=e.row_key, state=t("shap.anomaly") if e.is_anomaly else t("shap.normal"),
        score=e.anomaly_score))
    st.subheader(t("shap.explanation"))
    st.write(e.narrative)

    st.subheader(t("shap.proof"))
    labels = (read(run_id, "profiling.anomalies") or None)
    labels = labels.feature_labels if labels else {}
    var, val, sh = t("shap.variable"), t("shap.value"), t("shap.shap")
    df = pd.DataFrame([{var: label(c.feature, labels), val: c.value, sh: c.shap_value} for c in e.contributions])
    left, right = st.columns([3, 2])
    with left:
        fig, ax = plt.subplots(figsize=(6, 2.6))
        plot = df.iloc[::-1]
        ax.barh(plot[var], plot[sh], color=["#d62728" if v > 0 else "#1f77b4" for v in plot[sh]])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel(t("shap.axis"))
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    with right:
        st.dataframe(df.round(3), hide_index=True, width="stretch")
    st.caption(t("shap.footer", typical=-e.base_value, this=-e.model_output))
