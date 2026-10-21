"""app.py — BIFlow Streamlit shell (Samar).

Single-page Streamlit app that:
1. Accepts CSV upload + natural-language question.
2. Triggers the BIFlow DAG via orchestrator.dag_runner in a background thread.
3. Reads progress safely from the SQLite task store (thread-safe, no session_state mutation from worker).
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

# Process-level worker thread tracker (thread-safe, decoupled from session state)
_ACTIVE_THREADS: dict[str, Thread] = {}

# ── Session state helpers ────────────────────────────────────────────────
def _init_state():
    defaults = {
        "run_id": None,
        "running": False,
        "done": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

STEP_ORDER = execution_order()
STATUS_ICON = {
    "PENDING":      "⏳",
    "RUNNING":      "🔄",
    "SUCCESS":      "✅",
    "FAILED":       "❌",
    "SKIPPED":      "⏭️",
    "NEEDS_REVIEW": "⚠️",
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

    # Save uploaded files to a temp source dir
    source_dir = _REPO_ROOT / "runs" / run_id / "_upload_src"
    source_dir.mkdir(parents=True, exist_ok=True)
    for f in uploaded_files:
        (source_dir / f.name).write_bytes(f.read())

    # Start pipeline in a daemon thread — NO st.session_state mutations inside worker!
    worker = Thread(
        target=run_pipeline,
        kwargs={
            "run_id": run_id,
            "max_workers": 2,
            "params": {
                "source_dir": str(source_dir),
                "question": question,
                "uploaded_by": uploaded_by,
            },
        },
        daemon=True,
    )
    worker.start()
    _ACTIVE_THREADS[run_id] = worker

elif submitted and not uploaded_files:
    st.warning("Please upload at least one CSV file.")
elif submitted and not question:
    st.warning("Please enter a business question.")


# ── Progress display (Queried safely from SQLite) ──────────────────────────
run_id = st.session_state.get("run_id")
if run_id:
    st.divider()
    st.subheader(f"Run: `{run_id}`")

    # Read current state directly from SQLite task store
    task_records = get_run_status(run_id, db=DEFAULT_DB)
    status_by_step = {r["step"]: r for r in task_records}

    # Check worker thread status safely
    worker_thread = _ACTIVE_THREADS.get(run_id)
    thread_alive = worker_thread.is_alive() if worker_thread is not None else False

    TERMINAL_STATES = {"SUCCESS", "FAILED", "SKIPPED", "NEEDS_REVIEW"}
    n_done = sum(1 for s in STEP_ORDER if status_by_step.get(s, {}).get("status") in TERMINAL_STATES)
    total = len(STEP_ORDER)
    st.progress(n_done / total if total else 0, text=f"Steps completed: {n_done}/{total}")

    # One expander per step in DAG order
    for step in STEP_ORDER:
        info = status_by_step.get(step, {"status": "PENDING", "message": ""})
        icon = STATUS_ICON.get(info["status"], "❓")
        owner = STEPS.get(step, {})
        owner_name = getattr(owner, "owner", "?") if hasattr(owner, "owner") else "?"
        label = f"{icon} **{step}** `{info['status']}`  ·  owner: {owner_name}"
        with st.expander(label, expanded=(info["status"] == "RUNNING")):
            if info["message"]:
                st.caption(info["message"])
            else:
                st.caption("Waiting…")

    # If worker has completed, mark done
    if not thread_alive and task_records:
        st.session_state["running"] = False
        st.session_state["done"] = True

    # Auto-refresh while running
    if st.session_state.get("running"):
        time.sleep(1)
        st.rerun()


# ── Dashboard panels ──────────────────────────────────────────────────────
if st.session_state.get("done"):
    run_id = st.session_state["run_id"]
    spec_path = _REPO_ROOT / "runs" / run_id / "dashboard" / "dashboard_spec.json"

    if spec_path.exists():
        st.divider()
        st.subheader("📊 Dashboard")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))

        charts = spec.get("charts", spec.get("panels", []))
        for chart in charts:
            st.markdown(f"### {chart.get('title', 'Chart')}")
            chart_type = chart.get("chart_type", "bar")
            st.caption(f"Chart type: `{chart_type}` · Reason: {chart.get('reason', '')}")

            data_file = chart.get("data_file", "")
            data_path = Path(data_file)
            if not data_path.is_absolute():
                data_path = _REPO_ROOT / data_path

            if data_path.exists() and data_path.is_file():
                import pandas as pd
                try:
                    df = pd.read_parquet(data_path)
                    x_col = chart.get("x")
                    y_col = chart.get("y")
                    color_col = chart.get("color")

                    if chart_type == "kpi_card":
                        val = df[y_col].iloc[0] if (y_col and y_col in df.columns) else df.iloc[0, 0]
                        st.metric(label=chart.get("title", "KPI"), value=f"{val:,.2f}" if isinstance(val, (int, float)) else str(val))
                    elif chart_type == "line" and x_col and y_col and x_col in df.columns and y_col in df.columns:
                        st.line_chart(df[[x_col, y_col]].set_index(x_col))
                    elif chart_type == "bar" and x_col and y_col and x_col in df.columns and y_col in df.columns:
                        if color_col and color_col in df.columns:
                            # Grouped/faceted bar chart
                            st.bar_chart(df, x=x_col, y=y_col, color=color_col)
                        else:
                            st.bar_chart(df[[x_col, y_col]].set_index(x_col))
                    else:
                        st.dataframe(df)
                except Exception as ex:
                    st.warning(f"Could not render chart data: {ex}")
            else:
                st.info(f"Chart data file ({chart.get('data_file')}) is waiting for Analyst execution.")

        for warning in spec.get("warnings", []):
            msg = warning.get("message", str(warning)) if isinstance(warning, dict) else str(warning)
            st.warning(f"⚠️ {msg}")
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
