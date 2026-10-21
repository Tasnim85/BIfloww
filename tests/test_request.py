"""tests/test_request.py — Golden tests for semantic/request.py (Tâche 4).

Tests verified against the fixed implementation (calendar.monthrange, correct
month ordering, NEEDS_REVIEW on no-match, embeddings, and run(ctx) entrypoint).
"""
from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from semantic.request import _find_metric, _find_period, _make_period, _get_embedding_model, run
from contracts.agent import AgentStatus, RunContext
from contracts.common import save
from contracts.intake import Upload
from contracts.semantic import Glossary, KpiCatalog, load_yaml


# ── Fixtures ─────────────────────────────────────────────────────────────────
CATALOG_PATH = REPO_ROOT / "kpi" / "catalog.yaml"
GLOSSARY_PATH = REPO_ROOT / "semantic" / "glossary.yaml"


@pytest.fixture
def catalog() -> KpiCatalog:
    return load_yaml(KpiCatalog, CATALOG_PATH)


@pytest.fixture
def glossary() -> Glossary:
    return load_yaml(Glossary, GLOSSARY_PATH)


# ── _make_period: calendar.monthrange correctness ─────────────────────────────

def test_february_2018_end_day():
    """February 2018 is not a leap year — must end on the 28th, NOT 31."""
    period = _make_period("2018", "02")
    assert period.start == "2018-02-01"
    assert period.end   == "2018-02-28"
    # Validate that date.fromisoformat does not raise
    date.fromisoformat(period.start)
    date.fromisoformat(period.end)


def test_february_2020_end_day():
    """February 2020 IS a leap year — must end on the 29th."""
    period = _make_period("2020", "02")
    assert period.end == "2020-02-29"
    date.fromisoformat(period.end)


def test_august_end_day():
    """August always has 31 days."""
    period = _make_period("2018", "08")
    assert period.end == "2018-08-31"


def test_april_end_day():
    """April has 30 days."""
    period = _make_period("2018", "04")
    assert period.end == "2018-04-30"


# ── _find_period: month ordering ──────────────────────────────────────────────

def test_revenue_by_state_august_vs_july():
    """'Revenue by state in August vs July' → main=August, compare=July."""
    period, compare = _find_period("revenue by state in august vs july")
    assert period  is not None
    assert compare is not None
    assert period.start  == "2018-08-01"
    assert period.end    == "2018-08-31"
    assert compare.start == "2018-07-01"
    assert compare.end   == "2018-07-31"
    date.fromisoformat(period.start)
    date.fromisoformat(compare.end)


def test_revenue_in_february_2018():
    """'Revenue in February 2018' → period 2018-02-01 to 2018-02-28."""
    period, compare = _find_period("revenue in february 2018")
    assert period  is not None
    assert compare is None
    assert period.start == "2018-02-01"
    assert period.end   == "2018-02-28"   # NOT 31!
    date.fromisoformat(period.end)


def test_sales_september_compared_to_august():
    """'sales in september compared to august' → main=September, compare=August."""
    period, compare = _find_period("sales in september compared to august")
    assert period  is not None
    assert compare is not None
    assert period.start  == "2018-09-01"
    assert compare.start == "2018-08-01"
    date.fromisoformat(period.end)
    date.fromisoformat(compare.end)


def test_no_month_returns_none():
    """Questions with no month at all return (None, None)."""
    period, compare = _find_period("show me total sales for all time")
    assert period  is None
    assert compare is None


# ── _find_metric: NEEDS_REVIEW on no-match ───────────────────────────────────

def test_metric_found(catalog):
    """A recognized metric name returns (name, high_confidence)."""
    metric, conf = _find_metric("what is the total revenue by state", catalog)
    assert metric is not None
    assert conf >= 0.60


def test_metric_not_found_returns_none(catalog):
    """An unrecognizable question must return (None, 0.0) — no silent fallback."""
    metric, conf = _find_metric("xyzzy frob quux", catalog)
    assert metric is None
    assert conf   == 0.0


# ── Embedding search & run(ctx) entrypoint tests ─────────────────────────────

def test_embedding_search_model_available():
    """Verify SentenceTransformer model loads properly for semantic similarity search."""
    model = _get_embedding_model()
    # If installed, should load all-MiniLM-L6-v2
    assert model is not None, "SentenceTransformer model should load in offline or cached mode"


def test_run_without_period_returns_needs_review(tmp_path):
    """A question with a valid KPI but no time period must return NEEDS_REVIEW."""
    run_id = f"test_no_period_{uuid.uuid4().hex[:6]}"
    upload_dir = tmp_path / "upload"
    request_dir = tmp_path / "request"
    upload_dir.mkdir(parents=True)
    request_dir.mkdir(parents=True)

    upload = Upload(
        tables={"orders": "orders.csv"},
        question="Revenue by state",
        uploaded_by="tester",
    )
    upload_path = upload_dir / "upload.json"
    save(upload, upload_path)

    ctx = RunContext(
        run_id=run_id,
        agent="request",
        output_dir=request_dir,
        inputs={
            "upload": upload_path,
            "catalog": CATALOG_PATH,
            "glossary": GLOSSARY_PATH,
        },
    )

    agent_result = run(ctx)
    assert agent_result.status == AgentStatus.NEEDS_REVIEW
    assert "time period" in agent_result.message


def test_run_without_metric_returns_needs_review(tmp_path):
    """An unrecognizable question must return NEEDS_REVIEW."""
    run_id = f"test_no_metric_{uuid.uuid4().hex[:6]}"
    upload_dir = tmp_path / "upload"
    request_dir = tmp_path / "request"
    upload_dir.mkdir(parents=True)
    request_dir.mkdir(parents=True)

    upload = Upload(
        tables={"orders": "orders.csv"},
        question="xyzzy quux frob in August 2018",
        uploaded_by="tester",
    )
    upload_path = upload_dir / "upload.json"
    save(upload, upload_path)

    ctx = RunContext(
        run_id=run_id,
        agent="request",
        output_dir=request_dir,
        inputs={
            "upload": upload_path,
            "catalog": CATALOG_PATH,
            "glossary": GLOSSARY_PATH,
        },
    )

    agent_result = run(ctx)
    assert agent_result.status == AgentStatus.NEEDS_REVIEW
    assert "Could not match any KPI" in agent_result.message
