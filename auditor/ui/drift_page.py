"""Drift page: monthly runs against the reference months. Display only."""
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from auditor.drift import stats
from auditor.drift.monitor import monitor_runs
from auditor.drift.observe import observe_run
from auditor.ui.data import DRIFT_JOURNAL, read
from contracts.pipeline import RUNS_ROOT

STATUS = {"stable": "✅ stable", "data_drift": "🌊 les données ont changé",
          "data_drift_only": "🌊 données changées, décisions stables",
          "agent_changed": "⚙️ un agent a changé", "not_available": "—"}


@st.cache_resource(show_spinner="Lecture des runs (SHAP sur un échantillon de chaque mois)...")
def _observations(runs: tuple[str, ...], stamp: float):
    return {r: observe_run(r) for r in runs}


def render() -> None:
    st.title("Surveiller les agents dans le temps (drift)")
    st.caption("Comportement observé → comparaison avec les mois de référence → alerte → diagnostic de la cause")

    try:
        from auditor.dev.simulate_runs import MONITORED, REFERENCE, TRUTH_FILE, simulate
    except ImportError:
        st.error("Module de simulation introuvable.")
        return

    if not (RUNS_ROOT / REFERENCE[0]).exists():
        st.info("Les runs mensuels n'existent pas encore.")
        if st.button("Simuler les runs mensuels (données Olist réelles + 3 événements plantés)", type="primary"):
            with st.spinner("Un run par mois, d'octobre 2017 à août 2018..."):
                simulate()
            st.rerun()
        return
    if read(MONITORED[0], "auditor.drift") is None or not DRIFT_JOURNAL.exists():
        if st.button("Lancer le moniteur de drift", type="primary"):
            with st.spinner("Comparaison de chaque mois aux 6 mois de référence..."):
                monitor_runs(REFERENCE, MONITORED, journal=DRIFT_JOURNAL)
            st.rerun()
        return

    reports = {r: read(r, "auditor.drift") for r in MONITORED}
    truth = json.loads(TRUTH_FILE.read_text(encoding="utf-8")) if TRUTH_FILE.exists() else {}
    st.info(f"Référence : {REFERENCE[0]} → {REFERENCE[-1]} (6 mois). Le moniteur ne connaît pas les "
            "événements plantés : ils ne sont affichés ici que pour vérifier le résultat.")

    st.subheader("1. Diagnostic par mois")
    st.dataframe(pd.DataFrame([{
        "run": r, "diagnostic": STATUS.get(rep.status, rep.status),
        "agents signalés": ", ".join(rep.flagged_agents) or "-",
        "planté (démo uniquement)": truth.get(r, {}).get("what", "?")} for r, rep in reports.items()]),
        hide_index=True, width="stretch")

    st.subheader("2. Cartes de contrôle")
    runs = tuple(REFERENCE + MONITORED)
    stamp = max((RUNS_ROOT / r).stat().st_mtime for r in runs)
    obs = _observations(runs, stamp)
    metrics = sorted({k for o in obs.values() for k in o.metrics})
    key = st.selectbox("Indicateur", metrics, format_func=lambda k: f"{k[0]} · {k[1]}",
                       index=metrics.index(("profiling", "anomaly_rate")) if ("profiling", "anomaly_rate") in metrics else 0)
    ref_vals = [obs[r].metrics[key].value for r in REFERENCE if key in obs[r].metrics]
    center, lo, hi = stats.control_limits(ref_vals, min_rel_sigma=obs[REFERENCE[0]].metrics[key].min_rel_sigma)
    values = [obs[r].metrics[key].value if key in obs[r].metrics else None for r in runs]
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.axvspan(-0.5, len(REFERENCE) - 0.5, color="#cccccc", alpha=0.4, label="référence")
    ax.axhline(center, color="black", linewidth=0.8)
    ax.axhline(lo, color="#d62728", linestyle="--", linewidth=0.8, label="limites")
    ax.axhline(hi, color="#d62728", linestyle="--", linewidth=0.8)
    ax.plot(range(len(runs)), values, marker="o", color="#1f77b4")
    for i, v in enumerate(values):
        if v is not None and i >= len(REFERENCE) and not lo <= v <= hi:
            ax.plot(i, v, "o", color="#d62728", markersize=11)
    ax.set_xticks(range(len(runs)), [r[4:] for r in runs], rotation=45, fontsize=8)
    ax.set_title(f"{key[0]} · {key[1]}")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption("Limites = moyenne ± 3 écarts-types de la variation RÉELLE entre mois de référence "
               "(une p-chart donnait de fausses alertes : le taux d'anomalies varie naturellement de 0,7 à 1,4 %).")

    st.subheader("3. Données d'entrée (PSI)")
    st.dataframe(pd.DataFrame({r: {f"{c.agent}.{c.name}": round(c.psi, 3) for c in rep.input_checks}
                               for r, rep in reports.items()}), width="stretch")
    st.caption("PSI < 0,10 stable · 0,10 à 0,25 à surveiller · > 0,25 dérive (convention, pas une loi).")

    st.subheader("4. Diagnostic détaillé")
    run = st.selectbox("Mois", MONITORED, index=MONITORED.index("run_2018_05") if "run_2018_05" in MONITORED else 0)
    rep = reports[run]
    {"stable": st.success, "agent_changed": st.error}.get(rep.status, st.warning)(rep.narrative)
    out = [c for c in rep.metric_checks if c.out_of_control]
    if out:
        st.dataframe(pd.DataFrame([{"indicateur": f"{c.agent}.{c.name}", "valeur": c.value,
                                    "limite basse": c.lower, "limite haute": c.upper} for c in out]),
                     hide_index=True, width="stretch")
    st.caption("Astuce : dans « Demander pourquoi ? », choisis le journal « Drift mensuel » et ce run.")
