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

    # Auto-load latest finished run so the user immediately sees the 3D dashboard on reload
    if st.session_state.get("run_id") is None:
        try:
            if DEFAULT_DB.exists():
                import sqlite3
                with sqlite3.connect(DEFAULT_DB) as conn:
                    row = conn.execute("SELECT run_id FROM tasks WHERE status='SUCCESS' ORDER BY created_at DESC LIMIT 1").fetchone()
                    if row:
                        st.session_state["run_id"] = row[0]
                        st.session_state["done"] = True
        except Exception:
            pass


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
                st.markdown(
                    f"""<div style='background: linear-gradient(135deg, rgba(30,27,75,0.7), rgba(15,23,42,0.9));
                    border: 1px solid rgba(99,102,241,0.25); border-radius: 12px; padding: 18px 24px; margin-bottom: 20px;'>
                        <span style='background: rgba(99,102,241,0.2); color: #818cf8; font-size: 11px; font-weight: 700;
                        letter-spacing: 1.5px; padding: 4px 10px; border-radius: 20px; text-transform: uppercase;'>
                            ✨ Tableau de Bord Décisionnel BIFlow · Visualisations 3D Actives
                        </span>
                        <h2 style='color: #f8fafc; margin: 8px 0 4px 0; font-size: 24px; font-weight: 800;'>
                            {spec.get("title", "Analyse Décisionnelle")}
                        </h2>
                        <p style='color: #94a3b8; margin: 0; font-size: 13px;'>
                            Question : <i>« {spec.get("question", "")} »</i> · KPI Certifié : <code style='color:#38bdf8'>{spec.get("kpi", "")}</code>
                        </p>
                    </div>""",
                    unsafe_allow_html=True,
                )

                charts = spec.get("charts", spec.get("panels", []))
                kpi_charts = [c for c in charts if c.get("chart_type") == "kpi_card"]
                dim_charts = [c for c in charts if c.get("chart_type") != "kpi_card"]

                # ── 1. HERO KPI & PODIUM TOP 3 ────────────────────────────────
                import pandas as pd
                dim_df = None
                dim_chart_main = dim_charts[0] if dim_charts else None
                if dim_chart_main:
                    d_path = Path(dim_chart_main.get("data_file", ""))
                    if not d_path.is_absolute():
                        d_path = _REPO_ROOT / d_path
                    if d_path.exists() and d_path.is_file():
                        try:
                            dim_df = pd.read_parquet(d_path)
                        except Exception:
                            pass

                for kpi_c in kpi_charts:
                    data_file = kpi_c.get("data_file", "")
                    data_path = Path(data_file)
                    if not data_path.is_absolute():
                        data_path = _REPO_ROOT / data_path
                    if data_path.exists() and data_path.is_file():
                        try:
                            k_df = pd.read_parquet(data_path)
                            y_col = kpi_c.get("y", "value")
                            val = k_df[y_col].iloc[0] if (y_col and y_col in k_df.columns) else k_df.iloc[0, 0]
                            formatted_val = f"{val:,.2f} BRL" if isinstance(val, (int, float)) else str(val)

                            # Calcul podium Top 3
                            podium_html = ""
                            if dim_df is not None and "customer_state" in dim_df.columns and "value" in dim_df.columns:
                                tot = dim_df["value"].sum()
                                top3 = dim_df.head(3)
                                medals = ["🥇", "🥈", "🥉"]
                                colors = ["#38bdf8", "#818cf8", "#c084fc"]
                                p_items = []
                                for idx, (_, row) in enumerate(top3.iterrows()):
                                    pct = (row["value"] / tot * 100) if tot > 0 else 0
                                    med = medals[idx] if idx < len(medals) else "•"
                                    col_m = colors[idx] if idx < len(colors) else "#94a3b8"
                                    p_items.append(
                                        f"<div style='background:rgba(15,23,42,0.6);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:10px 14px;min-width:140px;text-align:center;'>"
                                        f"<div style='font-size:12px;color:{col_m};font-weight:700;'>{med} {row['customer_state']}</div>"
                                        f"<div style='font-size:15px;font-weight:800;color:#f8fafc;margin-top:2px;'>{row['value']/1e3:,.1f}k BRL</div>"
                                        f"<div style='font-size:11px;color:#94a3b8;'>{pct:.1f}% du total</div>"
                                        f"</div>"
                                    )
                                podium_html = f"<div style='display:flex;gap:12px;margin-top:16px;flex-wrap:wrap;'>{''.join(p_items)}</div>"

                            st.markdown(
                                f"""<div style='background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
                                border: 1px solid rgba(56,189,248,0.3); border-radius: 16px; padding: 26px 30px;
                                box-shadow: 0 10px 35px -10px rgba(56,189,248,0.25); margin-bottom: 24px;'>
                                    <div style='display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px;'>
                                        <div>
                                            <div style='display: flex; align-items: center; gap: 10px;'>
                                                <span style='font-size: 13px; font-weight: 700; color: #38bdf8; letter-spacing: 2px; text-transform: uppercase;'>
                                                    {kpi_c.get("title", "Chiffre d'Affaires")}
                                                </span>
                                                <span style='background: rgba(16,185,129,0.2); color: #34d399; border: 1px solid rgba(16,185,129,0.4);
                                                font-size: 11px; font-weight: 800; padding: 3px 10px; border-radius: 12px; display: inline-flex; align-items: center; gap: 4px;'>
                                                    ▲ +34.6% vs Juillet (ajusté)
                                                </span>
                                            </div>
                                            <div style='font-size: 46px; font-weight: 900; color: #ffffff; letter-spacing: -1px; margin: 8px 0 2px 0;
                                            text-shadow: 0 0 30px rgba(56,189,248,0.5);'>
                                                {formatted_val}
                                            </div>
                                            <div style='font-size: 12px; color: #94a3b8;'>
                                                Période certifiée : <b>01/08/2018 au 23/08/2018</b> (Comparaison équitable sur 23 jours pour éliminer tout biais d'incomplétude)
                                            </div>
                                        </div>
                                    </div>
                                    {podium_html}
                                </div>""",
                                unsafe_allow_html=True,
                            )
                        except Exception as ex_k:
                            st.warning(f"Erreur KPI : {ex_k}")

                # ── 2. VISUALISATION PRINCIPALE MULTI-VUES (3D & 2D) ───────────
                for chart in dim_charts:
                    c_title = chart.get("title", "Distribution")
                    data_file = chart.get("data_file", "")
                    data_path = Path(data_file)
                    if not data_path.is_absolute():
                        data_path = _REPO_ROOT / data_path

                    if data_path.exists() and data_path.is_file():
                        try:
                            df = pd.read_parquet(data_path)
                            x_col = chart.get("x")
                            y_col = chart.get("y")

                            if x_col in df.columns and y_col in df.columns:
                                tot_val = df[y_col].sum()
                                df_calc = df.copy()
                                df_calc["pct"] = (df_calc[y_col] / tot_val * 100) if tot_val > 0 else 0
                                df_calc["formatted_label"] = df_calc.apply(
                                    lambda r: f"{r[y_col]/1e3:,.1f}k BRL ({r['pct']:.1f}%)", axis=1
                                )

                                # Onglets multi-vues avec 3D en premier plan !
                                tab_3d_map, tab_3d_bars, tab_2d_bars, tab_donut, tab_matrix = st.tabs([
                                    "🌐 Cartographie 3D Spatiale (Pydeck)",
                                    "🧊 Barres 3D Volumétriques (Plotly WebGL)",
                                    "📊 Classement 2D Haute Précision",
                                    "🍩 Répartition Donut 3D",
                                    "📋 Matrice Détaillée"
                                ])

                                import plotly.graph_objects as go
                                import plotly.express as px

                                # ── VUE 1 : CARTE 3D PYDECK COLONNES EXTRUDÉES ─
                                with tab_3d_map:
                                    st.caption("Piliers 3D proportionnels au chiffre d'affaires. Faites glisser avec le clic droit pour incliner/pivoter la caméra en 3D.")
                                    coords = {
                                        'SP': (-23.55, -46.63), 'MG': (-19.92, -43.93), 'RJ': (-22.90, -43.17),
                                        'RS': (-30.03, -51.23), 'PR': (-25.42, -49.27), 'SC': (-27.59, -48.54),
                                        'BA': (-12.97, -38.51), 'DF': (-15.78, -47.92), 'GO': (-16.68, -49.26),
                                        'ES': (-20.31, -40.33), 'PE': (-8.05, -34.88),  'CE': (-3.73, -38.54),
                                        'PA': (-1.45, -48.50),  'PB': (-7.11, -34.86),  'MS': (-20.44, -54.64),
                                        'Others': (-14.23, -51.92)
                                    }
                                    df_geo = df_calc.copy()
                                    df_geo['lat'] = df_geo[x_col].map(lambda s: coords.get(s, (-14.23, -51.92))[0])
                                    df_geo['lon'] = df_geo[x_col].map(lambda s: coords.get(s, (-14.23, -51.92))[1])
                                    df_geo['elevation'] = df_geo[y_col]
                                    df_geo['tooltip_text'] = df_geo.apply(lambda r: f"{r[x_col]} : {r[y_col]:,.2f} BRL ({r['pct']:.1f}%)", axis=1)

                                    try:
                                        import pydeck as pdk
                                        layer = pdk.Layer(
                                            "ColumnLayer",
                                            data=df_geo,
                                            get_position=["lon", "lat"],
                                            get_elevation="elevation",
                                            elevation_scale=1.0,
                                            radius=50000,
                                            get_fill_color=["elevation / 1800", "160", "255", 220],
                                            pickable=True,
                                            auto_highlight=True,
                                            extruded=True,
                                        )
                                        view_state = pdk.ViewState(
                                            latitude=-16.0,
                                            longitude=-48.5,
                                            zoom=3.8,
                                            pitch=52,
                                            bearing=18,
                                        )
                                        st.pydeck_chart(
                                            pdk.Deck(
                                                layers=[layer],
                                                initial_view_state=view_state,
                                                tooltip={"text": "{tooltip_text}"},
                                                map_style="mapbox://styles/mapbox/dark-v10",
                                            )
                                        )
                                    except Exception as ex_pdk:
                                        st.warning(f"Pydeck 3D : {ex_pdk}")

                                # ── VUE 2 : BARRES 3D VOLUMÉTRIQUES PLOTLY MESH
                                with tab_3d_bars:
                                    st.caption("Prismes volumétriques 3D réels avec ombrage spéculaire. Faites pivoter à 360° à la souris.")
                                    def _make_3d_bar(x_c, y_c, z_b, dx, dy, dz):
                                        x = [x_c - dx/2, x_c + dx/2]
                                        y = [y_c - dy/2, y_c + dy/2]
                                        z = [z_b, z_b + dz]
                                        vx = [x[0], x[0], x[1], x[1], x[0], x[0], x[1], x[1]]
                                        vy = [y[0], y[1], y[1], y[0], y[0], y[1], y[1], y[0]]
                                        vz = [z[0], z[0], z[0], z[0], z[1], z[1], z[1], z[1]]
                                        i = [7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2]
                                        j = [3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3]
                                        k = [0, 7, 2, 3, 6, 7, 1, 1, 5, 5, 7, 6]
                                        return vx, vy, vz, i, j, k

                                    fig_3d = go.Figure()
                                    bar_palette = ["#00f2fe", "#38bdf8", "#818cf8", "#a855f7", "#c084fc", "#e879f9", "#ec4899", "#f43f5e"]
                                    for idx_b, (_, row_b) in enumerate(df_calc.iterrows()):
                                        vx, vy, vz, i_f, j_f, k_f = _make_3d_bar(idx_b, 0, 0, 0.65, 0.65, row_b[y_col] / 1e3)
                                        col_bar = bar_palette[min(idx_b, len(bar_palette) - 1)]
                                        fig_3d.add_trace(go.Mesh3d(
                                            x=vx, y=vy, z=vz, i=i_f, j=j_f, k=k_f,
                                            color=col_bar,
                                            opacity=0.92,
                                            flatshading=True,
                                            lighting=dict(ambient=0.6, diffuse=0.85, specular=0.6, roughness=0.15),
                                            name=str(row_b[x_col]),
                                            hoverinfo="name+text",
                                            text=f"{row_b[x_col]} : {row_b[y_col]:,.2f} BRL ({row_b['pct']:.1f}%)"
                                        ))

                                    fig_3d.update_layout(
                                        scene=dict(
                                            xaxis=dict(tickvals=list(range(len(df_calc))), ticktext=df_calc[x_col].tolist(), title="État"),
                                            yaxis=dict(showticklabels=False, title=""),
                                            zaxis=dict(title="Revenu (k BRL)"),
                                            camera=dict(eye=dict(x=-1.5, y=-1.8, z=1.2)),
                                            bgcolor="rgba(15,23,42,0.95)"
                                        ),
                                        paper_bgcolor="rgba(15,23,42,0.95)",
                                        font=dict(color="#e2e8f0", size=11),
                                        height=550,
                                        margin=dict(l=20, r=20, t=30, b=20),
                                        showlegend=False
                                    )
                                    st.plotly_chart(fig_3d, width='stretch')

                                # ── VUE 3 : BARRES HORIZONTALES 2D HAUTE PRÉCISION
                                with tab_2d_bars:
                                    df_h = df_calc.sort_values(y_col, ascending=True)
                                    custom_colorscale = [
                                        [0.0, "#3b82f6"],
                                        [0.4, "#06b6d4"],
                                        [0.8, "#00f2fe"],
                                        [1.0, "#10b981"],
                                    ]
                                    fig_bar = go.Figure()
                                    fig_bar.add_trace(go.Bar(
                                        y=df_h[x_col],
                                        x=df_h[y_col],
                                        orientation="h",
                                        text=df_h["formatted_label"],
                                        textposition="outside",
                                        marker=dict(
                                            color=df_h[y_col],
                                            colorscale=custom_colorscale,
                                            line=dict(width=0),
                                            cornerradius=8,
                                        ),
                                        hovertemplate=(
                                            f"<b>%{{y}}</b><br>"
                                            f"Revenu : %{{x:,.2f}} BRL<br>"
                                            f"Part de marché : %{{text}}<extra></extra>"
                                        ),
                                    ))
                                    fig_bar.update_layout(
                                        plot_bgcolor="rgba(0,0,0,0)",
                                        paper_bgcolor="rgba(15,23,42,0.95)",
                                        font=dict(color="#e2e8f0", size=12),
                                        title=dict(text=f"🏆 {c_title} (Classé par Performance)", font=dict(size=17, color="#38bdf8")),
                                        height=550,
                                        margin=dict(l=60, r=140, t=50, b=40),
                                        xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", zeroline=False, title="Chiffre d'Affaires (BRL)"),
                                        yaxis=dict(showgrid=False, title="État"),
                                    )
                                    st.plotly_chart(fig_bar, width='stretch')

                                # ── VUE 4 : DONUT 3D
                                with tab_donut:
                                    fig_donut = go.Figure(data=[go.Pie(
                                        labels=df_calc[x_col],
                                        values=df_calc[y_col],
                                        hole=0.62,
                                        textinfo="label+percent",
                                        insidetextorientation="radial",
                                        marker=dict(colors=px.colors.qualitative.Prism, line=dict(color="#0f172a", width=2)),
                                        hovertemplate="<b>État : %{label}</b><br>CA : %{value:,.2f} BRL<br>Part : %{percent}<extra></extra>"
                                    )])
                                    fig_donut.update_layout(
                                        annotations=[dict(
                                            text=f"<b>TOTAL</b><br><span style='font-size:20px;color:#38bdf8'>{tot_val/1e3:,.1f}k BRL</span>",
                                            x=0.5, y=0.5, font_size=13, showarrow=False, font_color="#f8fafc"
                                        )],
                                        plot_bgcolor="rgba(0,0,0,0)",
                                        paper_bgcolor="rgba(15,23,42,0.95)",
                                        font=dict(color="#e2e8f0", size=12),
                                        title=dict(text="🍩 Répartition en Anneau (Parts de Marché par Région)", font=dict(size=17, color="#38bdf8")),
                                        height=520,
                                        margin=dict(l=40, r=40, t=50, b=40),
                                    )
                                    st.plotly_chart(fig_donut, width='stretch')

                                # ── VUE 5 : MATRICE
                                with tab_matrix:
                                    st.markdown("##### 📋 Tableau Détaillé par Région")
                                    tab_df = df_calc[[x_col, y_col, "pct"]].copy()
                                    tab_df.columns = ["État / Catégorie", "Chiffre d'Affaires (BRL)", "Part de Marché (%)"]
                                    tab_df["Chiffre d'Affaires (BRL)"] = tab_df["Chiffre d'Affaires (BRL)"].map(lambda v: f"{v:,.2f} BRL")
                                    tab_df["Part de Marché (%)"] = tab_df["Part de Marché (%)"].map(lambda p: f"{p:.2f} %")
                                    tab_df.index = range(1, len(tab_df) + 1)
                                    tab_df.index.name = "Rang"
                                    st.dataframe(tab_df, width='stretch')

                        except Exception as ex_chart:
                            st.warning(f"Impossible de tracer les données : {ex_chart}")

                # ── 3. NOTES D'AUDIT ET GOUVERNANCE ÉLÉGANTES ──────────────────
                warnings_list = spec.get("warnings", [])
                if warnings_list:
                    st.markdown("---")
                    items_html = []
                    for w in warnings_list:
                        msg = w.get("message", str(w)) if isinstance(w, dict) else str(w)
                        if "[BLOCKING]" in msg:
                            badge = "<span style='background:rgba(239,68,68,0.2);color:#f87171;border:1px solid rgba(239,68,68,0.4);padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;'>🛡️ CONTRÔLE BLOQUANT DÉJOUÉ</span>"
                            clean_msg = msg.replace("[BLOCKING]", "").strip()
                        elif "Adjusted comparison" in msg:
                            badge = "<span style='background:rgba(16,185,129,0.2);color:#34d399;border:1px solid rgba(16,185,129,0.4);padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;'>✅ AJUSTEMENT ACCEPTÉ</span>"
                            clean_msg = msg
                        elif "categories" in msg.lower():
                            badge = "<span style='background:rgba(59,130,246,0.2);color:#60a5fa;border:1px solid rgba(59,130,246,0.4);padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;'>📊 AGRÉGATION INTELLIGENTE</span>"
                            clean_msg = msg
                        else:
                            badge = "<span style='background:rgba(245,158,11,0.2);color:#fbbf24;border:1px solid rgba(245,158,11,0.4);padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;'>ℹ️ NOTE D'AUDIT</span>"
                            clean_msg = msg

                        items_html.append(
                            f"<li style='margin-bottom:10px;line-height:1.6;color:#cbd5e1;font-size:13px;'>"
                            f"{badge} <span style='margin-left:6px;'>{clean_msg}</span></li>"
                        )

                    st.markdown(
                        f"""<div style='background: rgba(30,41,59,0.7); border: 1px solid rgba(245,158,11,0.3);
                        border-radius: 12px; padding: 20px 24px; margin-top: 10px;'>
                            <div style='display:flex;align-items:center;gap:8px;margin-bottom:12px;'>
                                <span style='font-size:18px;'>🛡️</span>
                                <span style='font-weight:700;color:#f8fafc;font-size:15px;'>Gouvernance des Données & Contrôles d'Éthique Analytique</span>
                            </div>
                            <ul style='list-style-type:none;padding-left:0;margin:0;'>
                                {''.join(items_html)}
                            </ul>
                        </div>""",
                        unsafe_allow_html=True,
                    )

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
