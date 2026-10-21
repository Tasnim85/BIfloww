"""tests/test_request.py — Golden tests for semantic/request.py (Tâche 4).

Tests verified against the fixed implementation (calendar.monthrange, correct
month ordering, NEEDS_REVIEW on no-match).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from semantic.request import _find_metric, _find_period, _make_period
from contracts.semantic import KpiCatalog, load_yaml


# ── Fixtures ─────────────────────────────────────────────────────────────────
CATALOG_PATH = REPO_ROOT / "contracts" / "examples" / "static" / "kpi" / "catalog.yaml"


@pytest.fixture
def catalog() -> KpiCatalog:
    return load_yaml(KpiCatalog, CATALOG_PATH)


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
