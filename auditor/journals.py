"""Which journal holds which run, and which run holds the data. Shared by the API and the UI.

Every journal lives in runs/ (git-ignored). The REAL journal is runs/audit_journal.db, the one the
orchestrator writes. The others are demos and must never be mixed with it.

Which journals are VISIBLE (API and Streamlit): the env variable BIFLOW_JOURNALS, ids separated by
commas. Default: all. In the team's production app: BIFLOW_JOURNALS=real,ui (no demo journal).
"""
import os
from pathlib import Path

from contracts.audit import read_events
from contracts.pipeline import RUNS_ROOT

JOURNALS = {  # id -> (French label, file name in runs/)
    "demo": ("Démo run_001", "demo_journal.db"),
    "drift": ("Drift mensuel", "drift_journal.db"),
    "clinics": ("Cliniques (2e jeu de données)", "clinics_journal.db"),
    "ui": ("Essais depuis l'interface", "ui_journal.db"),
    "real": ("Journal réel", "audit_journal.db"),
}
CUSTOM_JOURNAL = "ui"        # comparisons typed in the UI / API go there, never in the real journal


def journal_path(journal_id: str, runs_root: Path = RUNS_ROOT) -> Path:
    return Path(runs_root) / JOURNALS[journal_id][1]


def visible() -> list[str]:
    """Journal ids shown by the API and the UI (env BIFLOW_JOURNALS, default: all)."""
    wanted = [j.strip() for j in os.environ.get("BIFLOW_JOURNALS", "").split(",") if j.strip()]
    return [j for j in JOURNALS if j in wanted] if wanted else list(JOURNALS)


def existing(runs_root: Path = RUNS_ROOT) -> dict[str, Path]:
    """id -> path of the visible journals that exist."""
    paths = {j: journal_path(j, runs_root) for j in visible()}
    return {j: p for j, p in paths.items() if p.exists()}


def journal_id_for(run_id: str, runs_root: Path = RUNS_ROOT) -> str | None:
    """The journal that holds this run's decisions (first one found), else None."""
    for j, path in existing(runs_root).items():
        if read_events(path, run_id=run_id):
            return j
    return None


def journal_for(run_id: str, runs_root: Path = RUNS_ROOT, default: str | None = None) -> Path:
    """The journal of this run; if none holds it yet: the demo journal, or the real one when the
    demo journal is hidden (production)."""
    default = default or ("demo" if "demo" in visible() else "real")
    return journal_path(journal_id_for(run_id, runs_root) or default, runs_root)


def base_run(run_id: str, runs_root: Path = RUNS_ROOT) -> str:
    """Runs created from the UI/API reuse the data of another run (written in base_run.txt)."""
    marker = Path(runs_root) / run_id / "base_run.txt"
    return marker.read_text(encoding="utf-8").strip() if marker.exists() else run_id
