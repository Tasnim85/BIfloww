"""app.py — BIFlow Streamlit shell (Multi-Agent BI Platform).

Advanced Streamlit interface that:
1. Connects seamlessly with the BIFlow DAG orchestrator across all 13 agents.
2. Detects local Ollama / LLaMA 3 status in real time.
3. Provides 1-click loading for the Olist demonstration dataset (9 tables).
4. Features an interactive Human-in-the-Loop review panel for steps requiring human approval (NEEDS_REVIEW).
5. Displays live multi-phase DAG execution progress, step details, and artifact inspection.
6. Integrates Tasnim's Auditor components: Trust Badge, Comparison Banner, Audit Panel, and Causal Why-Box.
7. Renders the interactive BI dashboard from the DashboardSpec contract with KPI metrics, charts, and data export.

Run:
    streamlit run app/app.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from threading import Thread

import streamlit as st
import os as _os; _os.environ.setdefault('BIFLOW_SKIP_DUCKDB_VALIDATION', '1')

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Fix Streamlit package namespace collision: when running 'streamlit run app/app.py',
# Python registers 'app' as a single module without __path__, breaking subpackage imports like 'app.upload'.
_app_pkg_dir = str(_REPO_ROOT / "app")
if "app" in sys.modules and not hasattr(sys.modules["app"], "__path__"):
    sys.modules["app"].__path__ = [_app_pkg_dir]

# Load .env if present and ensure BO2_PII_SECRET has a valid 32+ char fallback for development
try:
    import dotenv
    dotenv.load_dotenv(_REPO_ROOT / ".env")
except Exception:
    pass

if not os.environ.get("BO2_PII_SECRET") or len(os.environ.get("BO2_PII_SECRET", "")) < 32:
    os.environ["BO2_PII_SECRET"] = "biflow_development_hmac_secret_key_32chars_min"

# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BIFlow — Multi-Agent BI Platform",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports ─────────────────────────────────────────────────────────────
from contracts.audit import DEFAULT_JOURNAL
from contracts.pipeline import RUNS_ROOT, STEPS, execution_order, output_path
from orchestrator.dag_runner import get_run_status, run_pipeline
from orchestrator.task_store import DEFAULT_DB

try:
    from auditor.ui.components import audit_panel, comparison_banner, trust_badge, why_box
    _AUDITOR_UI_AVAILABLE = True
except Exception:
    _AUDITOR_UI_AVAILABLE = False

# Process-level worker thread tracker across Streamlit reruns
@st.cache_resource
def _get_threads() -> dict[str, Thread]:
    return {}

_ACTIVE_THREADS = _get_threads()

# ── Theme and CSS Styling ───────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #e9ecef;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .status-pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .status-success { background-color: #d1e7dd; color: #0f5132; }
    .status-running { background-color: #cfe2ff; color: #084298; }
    .status-review { background-color: #fff3cd; color: #664d03; }
    .status-failed { background-color: #f8d7da; color: #842029; }
    .status-skipped { background-color: #e2e3e5; color: #41464b; }
    .phase-badge {
        font-size: 0.75rem;
        text-transform: uppercase;
        color: #6c757d;
        letter-spacing: 0.5px;
    }
</style>
""", unsafe_allow_html=True)


# ── Ollama Detection & Local AI Simulator ────────────────────────────────
def _ensure_local_ai_simulator():
    """Ensure Fake Ollama is running on port 11435 if real Ollama has no LLaMA 3."""
    try:
        url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
        with urllib.request.urlopen(url, timeout=1.0) as resp:
            data = json.load(resp)
            models = [m.get("name", "") for m in data.get("models", [])]
            if any("llama3" in m.lower() for m in models):
                return
    except Exception:
        pass

    try:
        from tools.integration.fake_ollama import H, ThreadingHTTPServer
        try:
            with urllib.request.urlopen("http://127.0.0.1:11435/api/tags", timeout=0.5) as r:
                os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11435"
                return
        except Exception:
            pass

        srv = ThreadingHTTPServer(("127.0.0.1", 11435), H)
        t = Thread(target=srv.serve_forever, daemon=True)
        t.start()
        os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11435"
    except Exception:
        pass

@st.cache_data(ttl=5, show_spinner=False)
def _check_ollama() -> tuple[bool, list[str]]:
    """Detect if local Ollama server is running and which models are pulled."""
    try:
        url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
        with urllib.request.urlopen(url, timeout=1.5) as response:
            data = json.load(response)
            models = [m.get("name", "") for m in data.get("models", [])]
            return True, models
    except Exception:
        return False, []


# ── Session State Helpers ────────────────────────────────────────────────
def _init_state():
    defaults = {
        "run_id": None,
        "running": False,
        "done": False,
        "source_mode": "sample",
        "question": "Revenue by state in August vs July",
        "uploaded_by": "Senior Analyst",
        "max_workers": 4,
        "stop_on_failure": False,
        "pipeline_params": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


def _resume_pipeline(run_id: str, params: dict) -> None:
    """Relance le DAG sur le même run_id (les étapes SUCCESS sont réutilisées)."""
    st.session_state["pipeline_params"] = params
    st.session_state["running"] = True
    st.session_state["done"] = False
    worker = Thread(
        target=run_pipeline,
        kwargs={
            "run_id": run_id,
            "max_workers": st.session_state["max_workers"],
            "params": params,
            "stop_on_failure": st.session_state["stop_on_failure"],
        },
        daemon=True,
    )
    worker.start()
    _ACTIVE_THREADS[run_id] = worker
    st.rerun()

STEP_ORDER = execution_order()
STATUS_ICON = {
    "PENDING":      "⏳",
    "RUNNING":      "🔄",
    "SUCCESS":      "✅",
    "FAILED":       "❌",
    "SKIPPED":      "⏭️",
    "NEEDS_REVIEW": "⚠️",
}

STEP_PHASES = {
    "upload":       "Phase 1: Ingestion",
    "similarity":   "Phase 1: Sémantique",
    "column_types": "Phase 1: Sémantique",
    "request":      "Phase 1: Requête",
    "pii":          "Phase 2: Gouvernance PII",
    "profiling":    "Phase 2: Qualité",
    "cleaning":     "Phase 2: Nettoyage",
    "etl":          "Phase 3: Entrepôt DuckDB",
    "lineage":      "Phase 3: Lignage",
    "analysis":     "Phase 4: Analyse & SQL",
    "comparisons":  "Phase 4: Comparaisons & Dérive",
    "auditor":      "Phase 4: Audit & XAI",
    "dashboard":    "Phase 5: Restitution BI",
}

# ── Sidebar ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://raw.githubusercontent.com/feathericons/feather/master/icons/activity.svg", width=40)
    st.title("BIFlow Studio")
    st.caption("Plateforme BI Multi-Agents & IA Décisionnelle")

    st.markdown("---")
    st.subheader("🤖 Statut IA Locale (Ollama)")
    ollama_ok, models = _check_ollama()
    has_llama3 = ollama_ok and any("llama3" in m.lower() for m in models)
    is_simulator = "11435" in os.environ.get("OLLAMA_BASE_URL", "")

    if has_llama3:
        if is_simulator:
            st.success("🟢 **Simulateur IA LLaMA 3 actif** (mode léger sans GPU)")
        else:
            st.success("🟢 **LLaMA 3 actif** (`llama3:latest` via Ollama)")
    else:
        if ollama_ok:
            st.warning(f"🟡 Ollama actif, mais LLaMA 3 absent. Modèles: {', '.join(models) or 'aucun'}")
        else:
            st.error("🔴 **Ollama hors ligne** (`http://127.0.0.1:11434`)")
        st.caption("Activez le simulateur IA local (LLaMA 3 sans GPU) pour tester tout le pipeline sans attendre le téléchargement :")
        if st.button("⚡ Activer le Simulateur IA Local", width='stretch', help="Démarre un test double de LLaMA 3 pour exécuter tout le pipeline sans GPU"):
            _ensure_local_ai_simulator()
            _check_ollama.clear()
            st.success("Simulateur démarré !")
            time.sleep(0.5)
            st.rerun()

    st.markdown("---")
    st.subheader("⚙️ Paramètres du DAG")
    max_workers = st.slider("Workers parallèles", min_value=1, max_value=8, value=st.session_state["max_workers"])
    st.session_state["max_workers"] = max_workers

    stop_on_fail = st.checkbox("Arrêt strict sur échec (stop_on_failure)", value=st.session_state["stop_on_failure"])
    st.session_state["stop_on_failure"] = stop_on_fail

    st.markdown("---")
    st.subheader("🕒 Historique des Runs")
    if DEFAULT_DB.exists():
        import sqlite3
        try:
            with sqlite3.connect(DEFAULT_DB) as conn:
                past_runs = [r[0] for r in conn.execute("SELECT DISTINCT run_id FROM tasks ORDER BY created_at DESC LIMIT 10").fetchall()]
            if past_runs:
                selected_run = st.selectbox("Inspecter un run précédent", options=["-- Sélectionner --"] + past_runs)
                if selected_run != "-- Sélectionner --":
                    if st.button("Charger ce run", width='stretch'):
                        st.session_state["run_id"] = selected_run
                        st.session_state["running"] = False
                        st.session_state["done"] = True
                        st.rerun()
            else:
                st.caption("Aucun run antérieur enregistré.")
        except Exception:
            pass


# ── Main Header ─────────────────────────────────────────────────────────
st.title("🔄 BIFlow — Orchestrateur Multi-Agents & BI")
st.markdown("Pipeline automatisé : **Ingestion** → **Similarité** → **Classification** → **Gouvernance PII** → **Nettoyage** → **ETL DuckDB** → **Analyste IA** → **Dashboard & Audit**")

# ── Launch Form ─────────────────────────────────────────────────────────
st.markdown("### 🚀 Nouveau Lancement")
tab_sample, tab_archive, tab_upload = st.tabs([
    "⚡ Mode Démo : Olist Sample (9 tables)",
    "📦 Dataset Complet : Archive Olist (125 Mo)",
    "📁 Mode Personnalisé : Téléversement / Dossier Local",
])

sample_dir = _REPO_ROOT / "data" / "sample"
archive_dir = Path(os.environ.get("BIFLOW_ARCHIVE_DIR", r"C:\Users\moham\Downloads\archive"))
source_dir: Path | None = None
uploaded_files = []

with tab_sample:
    st.markdown("Utilisez l'échantillon d'e-commerce Olist préparé (9 tables de test rapide).")
    if sample_dir.exists():
        csv_list = sorted(sample_dir.glob("*.csv"))
        st.info(f"**9 tables disponibles dans `data/sample/`** : {', '.join(c.stem for c in csv_list)}")
    else:
        st.warning("Répertoire `data/sample` non trouvé.")

with tab_archive:
    st.markdown("### 📦 Dataset Olist Réel Complet (125 Mo)")
    st.markdown(f"Emplacement détecté : `{archive_dir}`")
    if archive_dir.exists():
        archive_csvs = sorted(archive_dir.glob("*.csv"))
        total_mb = sum(f.stat().st_size for f in archive_csvs) / (1024 * 1024)
        st.success(f"**9 tables complètes prêtes ({total_mb:.1f} Mo)** : {', '.join(f.stem for f in archive_csvs)}")
        st.caption("Ce dataset contient les 100 000 commandes réelles, 1 000 000 de coordonnées géographiques, paiements, avis et vendeurs.")
    else:
        st.error(f"Dossier `{archive_dir}` introuvable.")

with tab_upload:
    custom_files = st.file_uploader(
        "Sélectionnez un ou plusieurs fichiers CSV",
        type=["csv"],
        accept_multiple_files=True,
        help="Déposez vos tables CSV brutes",
    )
    custom_folder_input = st.text_input(
        "Ou entrez le chemin absolu d'un dossier local de CSV :",
        value=str(archive_dir) if archive_dir.exists() else "",
    )

col_q, col_u = st.columns([3, 1])
with col_q:
    question = st.text_input(
        "Question analytique en langage naturel :",
        value=st.session_state["question"],
        placeholder="ex: Chiffre d'affaires par état en août 2018 (Revenue by state in August)",
    )
with col_u:
    user_name = st.text_input("Auteur du run :", value=st.session_state["uploaded_by"])

col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
with col_btn1:
    launch_sample = st.button("⚡ Lancer la Démo Olist", type="secondary", width='stretch')
with col_btn2:
    launch_archive = st.button("🚀 Lancer avec l'Archive Complète", type="primary", width='stretch', disabled=not archive_dir.exists())
with col_btn3:
    has_custom = bool(custom_files or (custom_folder_input and Path(custom_folder_input).is_dir()))
    launch_custom = st.button("▶ Lancer avec mes CSV téléversés", width='content', disabled=not has_custom)

# Trigger logic
trigger_run = False
target_source_dir: Path | None = None

if launch_sample:
    trigger_run = True
    target_source_dir = sample_dir
elif launch_archive:
    trigger_run = True
    target_source_dir = archive_dir
elif launch_custom:
    if custom_folder_input and Path(custom_folder_input).is_dir() and not custom_files:
        trigger_run = True
        target_source_dir = Path(custom_folder_input)
    elif custom_files:
        trigger_run = True
        temp_run_id = f"run_{uuid.uuid4().hex[:8]}"
        upload_dest = _REPO_ROOT / "runs" / temp_run_id / "_upload_src"
        upload_dest.mkdir(parents=True, exist_ok=True)
        for f in custom_files:
            (upload_dest / f.name).write_bytes(f.read())
        target_source_dir = upload_dest

if trigger_run and target_source_dir:
    new_run_id = f"run_{uuid.uuid4().hex[:8]}"
    st.session_state["run_id"] = new_run_id
    st.session_state["running"] = True
    st.session_state["done"] = False
    st.session_state["question"] = question
    st.session_state["uploaded_by"] = user_name

    if not (ollama_ok and has_llama3):
        _ensure_local_ai_simulator()
        _check_ollama.clear()

    pipeline_params = {
        "source_dir": str(target_source_dir),
        "question": question,
        "uploaded_by": user_name,
        "llm_model": "llama3:latest",
    }
    st.session_state["pipeline_params"] = pipeline_params

    # Launch daemon worker thread
    worker = Thread(
        target=run_pipeline,
        kwargs={
            "run_id": new_run_id,
            "max_workers": st.session_state["max_workers"],
            "params": pipeline_params,
            "stop_on_failure": st.session_state["stop_on_failure"],
        },
        daemon=True,
    )
    worker.start()
    _ACTIVE_THREADS[new_run_id] = worker
    st.rerun()


# ── Execution Tracker & Human-in-the-Loop Review ────────────────────────
run_id = st.session_state.get("run_id")
if run_id:
    st.markdown("---")
    st.subheader(f"📌 Suivi du Run : `{run_id}`")

    # Read current state directly from SQLite task store
    task_records = get_run_status(run_id, db=DEFAULT_DB)
    status_by_step = {r["step"]: r for r in task_records}

    # Check thread state
    worker_thread = _ACTIVE_THREADS.get(run_id)
    thread_alive = worker_thread.is_alive() if worker_thread is not None else False

    TERMINAL_STATES = {"SUCCESS", "FAILED", "SKIPPED", "NEEDS_REVIEW"}
    n_done = sum(1 for s in STEP_ORDER if status_by_step.get(s, {}).get("status") in TERMINAL_STATES)
    total_steps = len(STEP_ORDER)
    progress_val = min(1.0, max(0.0, n_done / total_steps if total_steps else 0.0))

    col_prog, col_stat = st.columns([4, 1])
    with col_prog:
        st.progress(progress_val, text=f"Progression globale : {n_done}/{total_steps} étapes terminées ({int(progress_val*100)}%)")
    with col_stat:
        if thread_alive:
            st.markdown('<span class="status-pill status-running">🔄 En cours</span>', unsafe_allow_html=True)
        elif any(r.get("status") == "NEEDS_REVIEW" for r in task_records):
            st.markdown('<span class="status-pill status-review">⚠️ Revue Humaine</span>', unsafe_allow_html=True)
        elif all(r.get("status") == "SUCCESS" for r in task_records if r.get("step") in STEP_ORDER):
            st.markdown('<span class="status-pill status-success">✅ Succès</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-pill status-skipped">⏹️ Arrêté</span>', unsafe_allow_html=True)

    # ── Human-in-the-Loop Review Panel ──────────────────────────────────
    review_steps = [s for s in STEP_ORDER if status_by_step.get(s, {}).get("status") == "NEEDS_REVIEW"]
    if review_steps and not thread_alive:
        st.warning("### ⚠️ Intervention Humaine Requise (Human-in-the-Loop)")
        reviewer = user_name or "ComplianceOfficer"

        for rev_step in review_steps:
            rev_info = status_by_step.get(rev_step, {})
            st.markdown(f"L'agent **{rev_step}** demande une validation humaine :")
            st.info(f"**Motif :** {rev_info.get('message', 'Validation humaine requise')}")

            proposal_path = _REPO_ROOT / "runs" / run_id / "etl" / "warehouse_proposal.json"

            # Montrer ce qu'on valide (ETL)
            if rev_step == "etl":
                st.info(
                    "🔒 **DuckDB est bloqué par la politique de sécurité Windows (WDAC).**\n\n"
                    "Le pipeline peut continuer en **mode Parquet-only** : les tables nettoyées "
                    "sont conservées sous forme de fichiers Parquet, l'analyse SQL sera exécutée "
                    "via pandas.\n\n"
                    "- ✅ **Approuver** → ETL continue sans DuckDB\n"
                    "- ❌ **Rejeter** → Pipeline arrêté"
                )
            elif rev_step == "comparisons":
                rep = _REPO_ROOT / "runs" / run_id / "comparisons" / "comparison_report.json"
                if rep.exists():
                    try:
                        data = json.loads(rep.read_text(encoding="utf-8"))
                        st.caption("⚖️ **Analyse de comparabilité temporelle :**")
                        st.write(data.get("summary", "Ajustement requis pour période incomplète."))
                    except Exception:
                        pass

            col_ok, col_ko = st.columns(2)

            # ── APPROUVER ──
            with col_ok:
                if st.button(f"✅ Approuver ({rev_step})", type="primary", key=f"ok_{run_id}_{rev_step}"):
                    params = dict(st.session_state.get("pipeline_params", {}))
                    try:
                        if rev_step == "pii":
                            params["uncertain_policy"] = "redact"
                        elif rev_step == "etl":
                            # If proposal file exists, hash it; otherwise use parquet-only fallback
                            if proposal_path.exists():
                                params["etl_approval"] = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
                            else:
                                # DuckDB unavailable → approve parquet-only warehouse mode
                                params["warehouse_mode"] = "parquet_only"
                                params["etl_approval"] = "parquet_only_approved"
                        elif rev_step == "comparisons":
                            from comparisons.checker import record_decision
                            record_decision(run_id, "accepted")
                    except Exception as exc:
                        st.error(f"Impossible d'enregistrer l'approbation : {exc}")
                    else:
                        _resume_pipeline(run_id, params)

            # ── REJETER ──
            with col_ko:
                if st.button(f"❌ Rejeter ({rev_step})", key=f"ko_{run_id}_{rev_step}"):
                    if rev_step == "comparisons":
                        from comparisons.checker import record_decision
                        record_decision(run_id, "rejected")
                        _resume_pipeline(run_id, dict(st.session_state.get("pipeline_params", {})))
                    else:
                        if rev_step == "etl":
                            proposal_path.unlink(missing_ok=True)   # forcera une nouvelle proposition
                        st.session_state["running"] = False
                        st.session_state["done"] = False
                        st.error(f"Proposition « {rev_step} » rejetée par {reviewer} : le pipeline reste arrêté. Lancez un nouveau run.")

    # ── Multi-Agent Step Accordion ──────────────────────────────────────
    st.markdown("#### 📋 Détail des Agents et Artéfacts")
    for step in STEP_ORDER:
        info = status_by_step.get(step, {"status": "PENDING", "message": ""})
        icon = STATUS_ICON.get(info["status"], "⏳")
        step_def = STEPS.get(step)
        owner_name = getattr(step_def, "owner", "Équipe BIFlow")
        phase = STEP_PHASES.get(step, "Exécution")

        expander_title = f"{icon} **{step}** — `{info['status']}` · *{phase}*"
        with st.expander(expander_title, expanded=(info["status"] in ("RUNNING", "NEEDS_REVIEW"))):
            default_msg = "Exécution en cours…" if info["status"] == "RUNNING" else "En attente..."
            st.markdown(f"**Message de statut :** {info.get('message') or default_msg}")

            # Inspect step outputs if available
            step_dir = _REPO_ROOT / "runs" / run_id / step
            if step_dir.exists() and step_def and step_def.outputs:
                st.markdown("##### 📦 Artéfacts produits :")
                for out_key, fname in step_def.outputs.items():
                    out_path = step_dir / fname.rstrip("/")
                    if out_path.exists():
                        if fname.endswith(".json") and out_path.is_file():
                            try:
                                json_data = json.loads(out_path.read_text(encoding="utf-8"))
                                st.caption(f"📄 `{fname}`")
                                st.json(json_data, expanded=False)
                            except Exception:
                                st.caption(f"📄 `{fname}` (Fichier JSON)")
                        elif fname.endswith(".parquet") and out_path.is_file():
                            st.caption(f"📊 `{fname}` (Table Parquet)")
                        elif fname.endswith("/") and out_path.is_dir():
                            files_count = len(list(out_path.glob("*")))
                            st.caption(f"📁 `{fname}` ({files_count} fichier(s))")
                    else:
                        st.caption(f"⏳ `{fname}` (Non encore généré)")

    # Complete worker detection
    if not thread_alive and task_records:
        st.session_state["running"] = False
        st.session_state["done"] = True

    # Auto-refresh loop while background worker runs
    if st.session_state.get("running"):
        time.sleep(1.2)
        st.rerun()


# ── Final Results, Dashboard & Auditor Panels ───────────────────────────
if st.session_state.get("done") and run_id:
    st.markdown("---")
    st.header("📊 Résultats Analytiques & Dashboard Final")

    tab_dash, tab_audit, tab_raw = st.tabs(["📈 Dashboard Décisionnel", "🛡️ Audit & Explicabilité (XAI)", "🔍 Données Brutes"])

    with tab_dash:
        spec_path = _REPO_ROOT / "runs" / run_id / "dashboard" / "dashboard_spec.json"
        if spec_path.exists():
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                st.subheader(spec.get("title", "Analyse Décisionnelle"))
                st.caption(f"Question traitée : *« {spec.get('question', '')} »* · KPI : `{spec.get('kpi', '')}`")

                charts = spec.get("charts", spec.get("panels", []))
                for chart in charts:
                    c_title = chart.get("title", "Graphique")
                    c_type = chart.get("chart_type", "bar")
                    st.markdown(f"#### {c_title}")
                    st.caption(f"Type : `{c_type}` · {chart.get('reason', '')}")

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

                            if c_type == "kpi_card":
                                val = df[y_col].iloc[0] if (y_col and y_col in df.columns) else df.iloc[0, 0]
                                formatted_val = f"{val:,.2f} BRL" if isinstance(val, (int, float)) else str(val)
                                col_kpi1, col_kpi2, col_kpi3 = st.columns([1, 2, 1])
                                with col_kpi2:
                                    st.markdown(
                                        f"""<div style='background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460);
                                        border-radius:16px;padding:32px 24px;text-align:center;
                                        box-shadow:0 8px 32px rgba(0,200,255,0.25);border:1px solid rgba(0,200,255,0.2)'>
                                        <div style='font-size:13px;letter-spacing:3px;color:#00c8ff;text-transform:uppercase;margin-bottom:8px'>{c_title}</div>
                                        <div style='font-size:42px;font-weight:900;color:#ffffff;text-shadow:0 0 20px rgba(0,200,255,0.8)'>{formatted_val}</div>
                                        </div>""",
                                        unsafe_allow_html=True,
                                    )
                            elif c_type == "bar" and x_col and y_col and x_col in df.columns and y_col in df.columns:
                                try:
                                    import plotly.express as px
                                    if color_col and color_col in df.columns:
                                        fig = px.bar(
                                            df.sort_values(y_col, ascending=False),
                                            x=x_col, y=y_col, color=color_col,
                                            barmode="group",
                                            animation_frame=color_col if df[color_col].nunique() > 1 else None,
                                            template="plotly_dark",
                                            color_discrete_sequence=px.colors.qualitative.Vivid,
                                            labels={x_col: x_col, y_col: y_col},
                                            height=480,
                                        )
                                    else:
                                        fig = px.bar(
                                            df.sort_values(y_col, ascending=False),
                                            x=x_col, y=y_col,
                                            template="plotly_dark",
                                            color=y_col,
                                            color_continuous_scale="Viridis",
                                            labels={x_col: x_col, y_col: y_col},
                                            height=480,
                                        )
                                    fig.update_layout(
                                        plot_bgcolor="rgba(0,0,0,0)",
                                        paper_bgcolor="rgba(26,26,46,0.95)",
                                        font=dict(color="#e0e0e0", size=12),
                                        title=dict(text=c_title, font=dict(size=18, color="#00c8ff")),
                                        bargap=0.25,
                                        bargroupgap=0.1,
                                    )
                                    fig.update_traces(marker_line_width=0)
                                    st.plotly_chart(fig, width='stretch')
                                except ImportError:
                                    import altair as alt
                                    chart_obj = alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#4C72B0").encode(
                                        x=alt.X(x_col, sort="-y"), y=alt.Y(y_col), tooltip=[x_col, y_col]
                                    ).properties(height=380)
                                    st.altair_chart(chart_obj, width='stretch')
                            elif c_type == "line" and x_col and y_col and x_col in df.columns and y_col in df.columns:
                                try:
                                    import plotly.express as px
                                    if color_col and color_col in df.columns:
                                        fig = px.line(df, x=x_col, y=y_col, color=color_col,
                                                      markers=True, template="plotly_dark",
                                                      color_discrete_sequence=px.colors.qualitative.Vivid,
                                                      height=480)
                                    else:
                                        fig = px.area(df, x=x_col, y=y_col,
                                                      template="plotly_dark", height=480,
                                                      color_discrete_sequence=["#00c8ff"])
                                    fig.update_layout(
                                        plot_bgcolor="rgba(0,0,0,0)",
                                        paper_bgcolor="rgba(26,26,46,0.95)",
                                        font=dict(color="#e0e0e0"),
                                        title=dict(text=c_title, font=dict(size=18, color="#00c8ff")),
                                    )
                                    st.plotly_chart(fig, width='stretch')
                                except ImportError:
                                    st.line_chart(df[[x_col, y_col]].set_index(x_col))
                            elif c_type == "pie" and x_col and y_col and x_col in df.columns and y_col in df.columns:
                                try:
                                    import plotly.express as px
                                    fig = px.pie(df, names=x_col, values=y_col,
                                                 template="plotly_dark", hole=0.4,
                                                 color_discrete_sequence=px.colors.qualitative.Vivid,
                                                 height=480)
                                    fig.update_layout(paper_bgcolor="rgba(26,26,46,0.95)", font=dict(color="#e0e0e0"))
                                    st.plotly_chart(fig, width='stretch')
                                except ImportError:
                                    st.dataframe(df, width='stretch')
                            else:
                                st.dataframe(df, width='stretch')
                        except Exception as ex:
                            st.warning(f"Impossible de tracer les données : {ex}")
                    else:
                        st.info("Données du graphique en attente de validation.")

                for warning in spec.get("warnings", []):
                    w_msg = warning.get("message", str(warning)) if isinstance(warning, dict) else str(warning)
                    st.warning(f"⚠️ {w_msg}")

            except Exception as exc:
                st.error(f"Erreur lors de la lecture du Dashboard : {exc}")
        else:
            st.info("DashboardSpec non disponible (le pipeline s'est arrêté avant l'étape Dashboard).")

    with tab_audit:
        st.subheader("🛡️ Explicabilité, Intégrité et Dérive")
        journal_path = _REPO_ROOT / "runs" / run_id / "journal.db"
        if not journal_path.exists():
            journal_path = _REPO_ROOT / DEFAULT_JOURNAL

        if _AUDITOR_UI_AVAILABLE and journal_path.exists():
            try:
                trust_badge(run_id, journal_path, key=f"tb_{run_id}")
                st.markdown("---")
                comparison_banner(run_id, journal_path, key=f"cb_{run_id}")
                st.markdown("---")
                why_box(run_id, journal_path, suggestions=["Pourquoi ce chiffre d'affaires ?", "Y a-t-il eu une dérive ?"], key=f"wb_{run_id}")
                st.markdown("---")
                audit_panel(run_id, journal_path, key=f"ap_{run_id}")
            except Exception as e:
                st.caption(f"Composants d'audit interactifs : {e}")
        else:
            st.info("Journal d'audit SQLite infalsifiable enregistré dans `runs/journal.db`.")

    with tab_raw:
        st.subheader("📋 Récapitulatif Exhaustif des Tâches")
        summary = get_run_status(run_id, db=DEFAULT_DB)
        if summary:
            import pandas as pd
            st.dataframe(pd.DataFrame(summary), width='stretch')
        else:
            st.caption("Aucun enregistrement trouvé dans la base des tâches.")
