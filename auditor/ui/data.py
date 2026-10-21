"""Shared helpers of the UI pages: where things are, what exists, texts. No business logic.

Every text of the app comes from the catalogs i18n/en.yaml and i18n/fr.yaml (section "ui"):
t("run.title") -> "Run result" or "Résultat d'un run", depending on the sidebar selector.
The app opens in BIFLOW_UI_LANG (default: English, the language of the demo).
"""
import os
from pathlib import Path

import streamlit as st

from auditor.journals import CUSTOM_JOURNAL, base_run, existing, journal_path  # noqa: F401 (base_run re-exported)
from auditor.journals import journal_for as _journal_for
from contracts.audit import read_events
from contracts.common import load
from contracts.i18n import LANGS, Msg, localize, render
from contracts.llm import LLMConfig
from contracts.pipeline import RUNS_ROOT, output_path
from contracts.registry import CONTRACT_OF

DEMO_JOURNAL = journal_path("demo")
DRIFT_JOURNAL = journal_path("drift")
CLINICS_JOURNAL = journal_path("clinics")         # 2nd dataset (python -m auditor.dev.make_clinics_demo)
UI_JOURNAL = journal_path(CUSTOM_JOURNAL)         # actions done from the UI on custom requests
TAMPER_COPY = RUNS_ROOT / "tamper_demo.db"        # the ONLY journal the tampering demo touches

UI_DEFAULT_LANG = os.environ.get("BIFLOW_UI_LANG", "en")
if UI_DEFAULT_LANG not in LANGS:
    UI_DEFAULT_LANG = "en"


def ui_lang() -> str:
    """Language of the app, chosen in the sidebar (en / fr)."""
    return st.session_state.get("lang", UI_DEFAULT_LANG)


def t(key: str, /, **params) -> str:
    """A text of the app in the chosen language (catalog section "ui")."""
    return render(Msg(key=f"ui.{key}", params=params), ui_lang())


def existing_journals() -> dict[str, Path]:
    """id -> path of the visible journals that exist (env BIFLOW_JOURNALS)."""
    return existing()


def pick_journal(key: str = "journal", prefer: str | None = None) -> Path | None:
    """prefer: a journal id ("demo", "drift", "clinics", "ui", "real")."""
    options = existing_journals()
    if not options:
        st.warning(t("common.no_journal"))
        return None
    ids = list(options)
    index = ids.index(prefer) if prefer in ids else 0
    return options[st.selectbox(t("common.journal"), ids, index=index, key=key,
                                format_func=lambda j: t(f"journal_names.{j}"))]


def journal_for(run_id: str) -> Path:
    """The journal that holds this run's decisions, else the demo journal."""
    return _journal_for(run_id)


def runs_in(journal: Path) -> list[str]:
    return sorted({e.run_id for e in read_events(journal)})


def runs_with(step: str, key: str) -> list[str]:
    if not RUNS_ROOT.exists():
        return []
    return sorted(p.name for p in RUNS_ROOT.iterdir()
                  if p.is_dir() and output_path(p.name, step, key).exists())


def read(run_id: str, ref: str):
    """Load an output of a run through its contract, in the UI language, or None if missing."""
    step, key = ref.split(".")
    path = output_path(run_id, step, key)
    return localize(load(CONTRACT_OF[ref], path), ui_lang()) if path.exists() else None


def llm_status() -> str:
    cfg = LLMConfig()
    if cfg.provider == "ollama":
        return f"Ollama · {cfg.model}"
    return f"{cfg.provider} · {cfg.model} · {t('common.key_present') if cfg.api_key() else t('common.key_missing')}"


def source_badge(source: str) -> str:
    return t("common.llm_written") if source.startswith("llm:") else t("common.template")


def need(paths: dict[str, Path]) -> bool:
    """Show what is missing and how to create it. True if everything exists."""
    missing = {k: p for k, p in paths.items() if not Path(p).exists()}
    for label, path in missing.items():
        st.error(t("common.missing", label=label, path=str(path)))
    if missing:
        st.info(t("common.prep") + "\n\n"
                "```\npython -m contracts.examples.install\npython -m auditor.dev.make_fake_inputs\n"
                "python -m auditor.dev.seed_demo_journal\npython -m auditor.dev.simulate_runs\n```")
    return not missing

