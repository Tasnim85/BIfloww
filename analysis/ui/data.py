"""Where things are and how to read them, for Rabeb's pages. No business logic here."""
from pathlib import Path

import pandas as pd

from analysis.ui.texts import t
from contracts.audit import DEFAULT_JOURNAL, read_events
from contracts.common import load
from contracts.llm import LLMConfig
from contracts.pipeline import RUNS_ROOT, context_for, output_path
from contracts.registry import CONTRACT_OF
from contracts.semantic import Glossary, KpiCatalog, load_yaml

GLOSSARY = Path(__file__).resolve().parents[2] / "semantic" / "glossary.yaml"


def read(run_id: str, ref: str):
    """An output of a run, validated by its contract, or None if it does not exist yet."""
    step, key = ref.split(".")
    path = output_path(run_id, step, key)
    return load(CONTRACT_OF[ref], path) if path.exists() else None


def result_table(run_id: str) -> pd.DataFrame | None:
    path = output_path(run_id, "analysis", "data")
    return pd.read_parquet(path) if path.exists() else None


def runs_with(step: str, key: str) -> list[str]:
    if not RUNS_ROOT.exists():
        return []
    return sorted(p.name for p in RUNS_ROOT.iterdir() if p.is_dir() and output_path(p.name, step, key).exists())


def catalog(run_id: str = "dev_001") -> KpiCatalog:
    return load_yaml(KpiCatalog, context_for("analysis", run_id).inputs["catalog"])


def glossary() -> Glossary | None:
    return load_yaml(Glossary, GLOSSARY) if GLOSSARY.exists() else None


def insight_source(run_id: str, journal: Path = DEFAULT_JOURNAL) -> str | None:
    """"llm" or "fallback": read from the journal entry the Analyst wrote last for this run."""
    written = [e for e in read_events(journal, run_id=run_id, agent="analysis") if e.step == "insights_written"]
    return written[-1].evidence.get("source") if written else None


def llm_status() -> str:
    cfg = LLMConfig()
    if cfg.provider == "ollama":
        return f"Ollama · {cfg.model}"
    return f"{cfg.provider} · {cfg.model} · {t('common.key_present') if cfg.api_key() else t('common.key_missing')}"
