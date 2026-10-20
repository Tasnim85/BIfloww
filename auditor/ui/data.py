"""Shared helpers of the UI pages: where things are, what exists. No business logic."""
from pathlib import Path

import streamlit as st

from contracts.audit import DEFAULT_JOURNAL, read_events
from contracts.common import load
from contracts.llm import LLMConfig
from contracts.pipeline import RUNS_ROOT, output_path
from contracts.registry import CONTRACT_OF

DEMO_JOURNAL = RUNS_ROOT / "demo_journal.db"
DRIFT_JOURNAL = RUNS_ROOT / "drift_journal.db"
UI_JOURNAL = RUNS_ROOT / "ui_journal.db"          # actions done from the UI on custom requests
CLINICS_JOURNAL = RUNS_ROOT / "clinics_journal.db"  # 2nd dataset (python -m auditor.dev.make_clinics_demo)
TAMPER_COPY = RUNS_ROOT / "tamper_demo.db"        # the ONLY journal the tampering demo touches

JOURNALS = {
    "Démo run_001": DEMO_JOURNAL,
    "Drift mensuel": DRIFT_JOURNAL,
    "Cliniques (2e jeu de données)": CLINICS_JOURNAL,
    "Essais depuis l'interface": UI_JOURNAL,
    "Journal réel": DEFAULT_JOURNAL,
}


def existing_journals() -> dict[str, Path]:
    return {k: p for k, p in JOURNALS.items() if p.exists()}


def pick_journal(label: str = "Journal", key: str = "journal", prefer: str | None = None) -> Path | None:
    options = existing_journals()
    if not options:
        st.warning("Aucun journal trouvé. Lance `python -m auditor.dev.seed_demo_journal`.")
        return None
    names = list(options)
    index = names.index(prefer) if prefer in names else 0
    return options[st.selectbox(label, names, index=index, key=key)]


def journal_for(run_id: str) -> Path:
    """The journal that holds this run's decisions (first one found), else the demo journal."""
    for path in existing_journals().values():
        if read_events(path, run_id=run_id):
            return path
    return DEMO_JOURNAL


def base_run(run_id: str) -> str:
    """Runs created from the UI reuse the data of another run (written in base_run.txt)."""
    marker = RUNS_ROOT / run_id / "base_run.txt"
    return marker.read_text(encoding="utf-8").strip() if marker.exists() else run_id


def runs_in(journal: Path) -> list[str]:
    return sorted({e.run_id for e in read_events(journal)})


def runs_with(step: str, key: str) -> list[str]:
    if not RUNS_ROOT.exists():
        return []
    return sorted(p.name for p in RUNS_ROOT.iterdir()
                  if p.is_dir() and output_path(p.name, step, key).exists())


def read(run_id: str, ref: str):
    """Load an output of a run through its contract, or None if it does not exist."""
    step, key = ref.split(".")
    path = output_path(run_id, step, key)
    return load(CONTRACT_OF[ref], path) if path.exists() else None


def llm_status() -> str:
    cfg = LLMConfig()
    if cfg.provider == "ollama":
        return f"Ollama · {cfg.model}"
    return f"{cfg.provider} · {cfg.model} · clé {'présente' if cfg.api_key() else 'ABSENTE'}"


def source_badge(source: str) -> str:
    return ("🤖 rédigé par le LLM, vérifié" if source.startswith("llm:")
            else "📋 gabarit déterministe")


def need(paths: dict[str, Path]) -> bool:
    """Show what is missing and how to create it. True if everything exists."""
    missing = {k: p for k, p in paths.items() if not Path(p).exists()}
    for label, path in missing.items():
        st.error(f"Manquant : {label} (`{path}`)")
    if missing:
        st.info("Commandes de préparation, depuis la racine du projet :\n\n"
                "```\npython -m contracts.examples.install\npython -m auditor.dev.make_fake_inputs\n"
                "python -m auditor.dev.seed_demo_journal\npython -m auditor.dev.simulate_runs\n```")
    return not missing

