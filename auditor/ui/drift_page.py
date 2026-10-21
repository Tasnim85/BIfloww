"""Drift page: monthly runs against the reference months. Display only."""
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from auditor.drift import stats
from auditor.drift.monitor import monitor_runs
from auditor.drift.observe import observe_run
from auditor.ui.data import DRIFT_JOURNAL, read, t
from contracts.pipeline import RUNS_ROOT

ICON = {"stable": "✅", "data_drift": "🌊", "data_drift_only": "🌊", "agent_changed": "⚙️", "not_available": ""}


def status_label(status: str) -> str:
    return f"{ICON.get(status, '')} {t('drift_status.' + status)}".strip()


@st.cache_resource(show_spinner=False)
def _observations(runs: tuple[str, ...], stamp: float):
    return {r: observe_run(r) for r in runs}


def render() -> None:
    st.title(t("dr.title"))
    st.caption(t("dr.caption"))

    try:
        from auditor.dev.simulate_runs import MONITORED, REFERENCE, TRUTH_FILE, simulate
    except ImportError:
        st.error(t("dr.no_module"))
        return

    if not (RUNS_ROOT / REFERENCE[0]).exists():
        st.info(t("dr.no_runs"))
        if st.button(t("dr.simulate"), type="primary"):
            with st.spinner(t("dr.simulating")):
                simulate()
            st.rerun()
        return
    if read(MONITORED[0], "auditor.drift") is None or not DRIFT_JOURNAL.exists():
        if st.button(t("dr.monitor"), type="primary"):
            with st.spinner(t("dr.monitoring")):
                monitor_runs(REFERENCE, MONITORED, journal=DRIFT_JOURNAL)
            st.rerun()
        return

    reports = {r: read(r, "auditor.drift") for r in MONITORED}
    truth = json.loads(TRUTH_FILE.read_text(encoding="utf-8")) if TRUTH_FILE.exists() else {}
    st.info(t("dr.reference", first=REFERENCE[0], last=REFERENCE[-1]))

    st.subheader(t("dr.by_month"))
    st.dataframe(pd.DataFrame([{
        "run": r, t("dr.diagnosis"): status_label(rep.status),
        t("dr.flagged"): ", ".join(rep.flagged_agents) or "-",
        t("dr.planted"): truth.get(r, {}).get("what", "?")} for r, rep in reports.items()]),
        hide_index=True, width="stretch")

    st.subheader(t("dr.charts"))
    runs = tuple(REFERENCE + MONITORED)
    stamp = max((RUNS_ROOT / r).stat().st_mtime for r in runs)
    with st.spinner(t("dr.reading")):
        obs = _observations(runs, stamp)
    metrics = sorted({k for o in obs.values() for k in o.metrics})
    key = st.selectbox(t("dr.indicator"), metrics, format_func=lambda k: f"{k[0]} · {k[1]}",
                       index=metrics.index(("profiling", "anomaly_rate")) if ("profiling", "anomaly_rate") in metrics else 0)
    ref_vals = [obs[r].metrics[key].value for r in REFERENCE if key in obs[r].metrics]
    center, lo, hi = stats.control_limits(ref_vals, min_rel_sigma=obs[REFERENCE[0]].metrics[key].min_rel_sigma)
    values = [obs[r].metrics[key].value if key in obs[r].metrics else None for r in runs]
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.axvspan(-0.5, len(REFERENCE) - 0.5, color="#cccccc", alpha=0.4, label=t("dr.ref_band"))
    ax.axhline(center, color="black", linewidth=0.8)
    ax.axhline(lo, color="#d62728", linestyle="--", linewidth=0.8, label=t("dr.limits"))
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
    st.caption(t("dr.charts_caption"))

    st.subheader(t("dr.psi"))
    st.dataframe(pd.DataFrame({r: {f"{c.agent}.{c.name}": round(c.psi, 3) for c in rep.input_checks}
                               for r, rep in reports.items()}), width="stretch")
    st.caption(t("dr.psi_caption"))

    st.subheader(t("dr.detail"))
    run = st.selectbox(t("dr.month"), MONITORED, index=MONITORED.index("run_2018_05") if "run_2018_05" in MONITORED else 0)
    rep = reports[run]
    {"stable": st.success, "agent_changed": st.error}.get(rep.status, st.warning)(rep.narrative)
    out = [c for c in rep.metric_checks if c.out_of_control]
    if out:
        st.dataframe(pd.DataFrame([{t("dr.indicator"): f"{c.agent}.{c.name}", t("dr.value"): c.value,
                                    t("dr.low"): c.lower, t("dr.high"): c.upper} for c in out]),
                     hide_index=True, width="stretch")
    st.caption(t("dr.tip"))
