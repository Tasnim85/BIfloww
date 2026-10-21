"""app.py — BIFlow Streamlit shell (Samar).

Single-page Streamlit app that:
1. Accepts CSV upload + natural-language question.
2. Triggers the BIFlow DAG via orchestrator.dag_runner.
3. Shows real-time step-by-step progress (one expander per step).
4. Renders the dashboard panels from the DashboardSpec contract.

Run:
    streamlit run app/app.py
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from threading import Thread

import streamlit as st

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BIFlow",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Imports (after sys.path fix) ─────────────────────────────────────────
from contracts.pipeline import STEPS, execution_order
from orchestrator.dag_runner import get_run_status, run_pipeline
from orchestrator.task_store import DEFAULT_DB


# ── Session state helpers ────────────────────────────────────────────────
def _init_state():
    defaults = {
        "run_id": None,
        "running": False,
        "progress": {},   # step → {status, message}
        "done": False,
        "spec_path": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

STEP_ORDER = execution_order()
STATUS_ICON = {
    "PENDING":  "⏳",
    "RUNNING":  "🔄",
    "SUCCESS":  "✅",
    "FAILED":   "❌",
    "SKIPPED":  "⏭️",
}


# ── Header ───────────────────────────────────────────────────────────────
st.title("🔄 BIFlow — Intelligent BI Automation")
st.caption("Multi-agent pipeline: upload → profile → clean → ETL → analyze → dashboard")

# ── Upload & Question form ────────────────────────────────────────────────
with st.form("upload_form", clear_on_submit=False):
    col1, col2 = st.columns([2, 3])
    with col1:
        uploaded_files = st.file_uploader(
            "Upload CSV tables", type=["csv"], accept_multiple_files=True
        )
    with col2:
        question = st.text_input(
            "Your business question",
            placeholder="e.g. Revenue by state in August vs July",
        )
        uploaded_by = st.text_input("Your name", value="anonymous")

    submitted = st.form_submit_button("▶ Run BIFlow Pipeline", type="primary")


# ── Pipeline trigger ──────────────────────────────────────────────────────
if submitted and uploaded_files and question:
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    st.session_state["run_id"] = run_id
    st.session_state["running"] = True
    st.session_state["done"] = False
    st.session_state["progress"] = {s: {"status": "PENDING", "message": ""} for s in STEP_ORDER}

    # Save uploaded files to a temp source dir
    source_dir = _REPO_ROOT / "runs" / run_id / "_upload_src"
    source_dir.mkdir(parents=True, exist_ok=True)
    for f in uploaded_files:
        (source_dir / f.name).write_bytes(f.read())

    # Progress callback (updates session state from background thread)
    def _callback(step, status, message):
        st.session_state["progress"][step] = {"status": status, "message": message}

    # Run in background thread so Streamlit can refresh
    def _run():
        try:
            run_pipeline(
                run_id=run_id,
                max_workers=2,
                params={
                    "source_dir": str(source_dir),
                    "question": question,
                    "uploaded_by": uploaded_by,
                },
                callback=_callback,
            )
        finally:
            st.session_state["running"] = False
            st.session_state["done"] = True

    Thread(target=_run, daemon=True).start()

elif submitted and not uploaded_files:
    st.warning("Please upload at least one CSV file.")
elif submitted and not question:
    st.warning("Please enter a business question.")


# ── Progress display ──────────────────────────────────────────────────────
if st.session_state["run_id"]:
    st.divider()
    st.subheader(f"Run: `{st.session_state['run_id']}`")

    progress = st.session_state["progress"]
    n_done = sum(1 for v in progress.values() if v["status"] in ("SUCCESS", "FAILED", "SKIPPED"))
    total  = len(STEP_ORDER)
    st.progress(n_done / total if total else 0, text=f"Steps: {n_done}/{total}")

    # One expander per step in DAG order
    for step in STEP_ORDER:
        info = progress.get(step, {"status": "PENDING", "message": ""})
        icon = STATUS_ICON.get(info["status"], "❓")
        owner = STEPS.get(step, {})
        owner_name = getattr(owner, "owner", "?") if hasattr(owner, "owner") else "?"
        label = f"{icon} **{step}** `{info['status']}`  ·  owner: {owner_name}"
        with st.expander(label, expanded=(info["status"] == "RUNNING")):
            if info["message"]:
                st.caption(info["message"])
            else:
                st.caption("Waiting…")

    # Auto-refresh while running
    if st.session_state["running"]:
        time.sleep(1)
        st.rerun()


# ── Dashboard panels ──────────────────────────────────────────────────────
if st.session_state["done"]:
    run_id = st.session_state["run_id"]
    spec_path = _REPO_ROOT / "runs" / run_id / "dashboard" / "dashboard_spec.json"

    if spec_path.exists():
        st.divider()
        st.subheader("📊 Dashboard")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))

        for panel in spec.get("panels", []):
            st.markdown(f"### {panel.get('title', 'Chart')}")
            st.caption(f"Chart type: `{panel.get('chart_type')}` · "
                       f"Metric: `{panel.get('metric')}`")

            data_file = panel.get("data_file", "")
            if data_file and Path(data_file).exists():
                import pandas as pd
                df = pd.read_parquet(data_file)
                dims = panel.get("dimensions", [])
                chart_type = panel.get("chart_type", "bar_chart")
                if dims and panel.get("metric") in df.columns:
                    x_col = dims[0]
                    y_col = panel["metric"]
                    chart_df = df[[x_col, y_col]].set_index(x_col)
                    if chart_type == "line_chart":
                        st.line_chart(chart_df)
                    elif chart_type == "heatmap":
                        st.dataframe(chart_df)
                    else:
                        st.bar_chart(chart_df)
                else:
                    st.dataframe(df.head(20))
            else:
                st.info("Result data not available yet.")

        for warning in spec.get("warnings", []):
            level = warning.get("level", "warning")
            msg   = warning.get("message", "")
            fix   = warning.get("fix")
            if level == "error":
                st.error(f"⚠️ {msg}" + (f"\n\n**Proposed fix:** {fix}" if fix else ""))
            else:
                st.warning(f"⚠️ {msg}" + (f"\n\n**Proposed fix:** {fix}" if fix else ""))
    else:
        st.info("Dashboard spec not yet available. The pipeline may still be running or some steps failed.")

    # Full run summary
    with st.expander("📋 Full Run Summary"):
        summary = get_run_status(run_id, db=DEFAULT_DB)
        import pandas as pd
        if summary:
            st.dataframe(pd.DataFrame(summary), use_container_width=True)
        else:
            st.caption("No task records found.")
