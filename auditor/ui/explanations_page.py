"""SHAP page: why was this row flagged? Display only."""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from auditor.ui.data import read, runs_with
from auditor.xai.explain import build_report
from auditor.xai.narrator import label
from contracts.common import save
from contracts.pipeline import context_for, output_path


def render() -> None:
    st.title("Expliquer une anomalie (SHAP)")
    st.caption("Décision (profiling) → explication SHAP → preuve → journal. "
               "L'Auditor explique la décision, il ne la change jamais.")

    runs = runs_with("profiling", "anomalies")
    if not runs:
        st.error("Aucune sortie de profiling. Lance `python -m auditor.dev.make_fake_inputs`.")
        return
    run_id = st.selectbox("Run", runs, index=runs.index("run_001") if "run_001" in runs else 0)

    report = read(run_id, "auditor.explanations")
    if report is None:
        st.info("Les explications de ce run n'ont pas encore été calculées.")
        if st.button("Calculer les explications SHAP", type="primary"):
            ctx = context_for("auditor", run_id)
            with st.spinner("SHAP sur toutes les anomalies..."):
                save(build_report(ctx.inputs["anomalies"], ctx.inputs["model"], ctx.inputs["scores"]),
                     output_path(run_id, "auditor", "explanations"))
            st.rerun()
        return

    anomalies = [e for e in report.explanations if e.is_anomaly]
    normals = [e for e in report.explanations if not e.is_anomaly]
    c1, c2, c3 = st.columns(3)
    c1.metric("Anomalies expliquées", len(anomalies))
    c2.metric("Lignes normales (comparaison)", len(normals))
    c3.metric("Modèle", report.model_version)
    st.success("Le score est reconstruit à partir de SHAP pour chaque ligne (écart < 1e-6) : "
               "l'explication porte sur la décision réelle.")

    scope = st.radio("Quelles lignes ?", ["Anomalies (les plus fortes d'abord)", "Lignes normales"],
                     horizontal=True)
    rows = anomalies if scope.startswith("Anomalies") else normals
    if not rows:
        st.info("Aucune ligne dans cette catégorie.")
        return
    e = st.selectbox("Ligne", rows[:200], format_func=lambda x: f"{x.row_key} · score {x.anomaly_score:.3f}")

    (st.error if e.is_anomaly else st.success)(
        f"{e.row_key} : {'anomalie' if e.is_anomaly else 'normale'} (score {e.anomaly_score:.3f})")
    st.subheader("Explication")
    st.write(e.narrative)

    st.subheader("Preuve : contributions SHAP")
    labels = (read(run_id, "profiling.anomalies") or None)
    labels = labels.feature_labels if labels else {}
    df = pd.DataFrame([{"Variable": label(c.feature, labels), "Valeur": c.value, "SHAP (coupes)": c.shap_value}
                       for c in e.contributions])
    left, right = st.columns([3, 2])
    with left:
        fig, ax = plt.subplots(figsize=(6, 2.6))
        plot = df.iloc[::-1]
        ax.barh(plot["Variable"], plot["SHAP (coupes)"],
                color=["#d62728" if v > 0 else "#1f77b4" for v in plot["SHAP (coupes)"]])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("rouge = vers l'anomalie, bleu = vers la normale")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    with right:
        st.dataframe(df.round(3), hide_index=True, width="stretch")
    st.caption(f"Ligne typique isolée en {-e.base_value:.1f} coupes, celle-ci en {-e.model_output:.1f}. "
               "SHAP explique le score du modèle, pas une vérité métier.")
