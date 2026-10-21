"""test_execution_order.py -- Verify contracts.pipeline.execution_order().

Confirms prerequisites always appear before dependents in the topological
sort, and that the list is complete.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.pipeline import STEPS, execution_order


def _idx(order: list[str], name: str) -> int:
    return order.index(name)


def test_execution_order_contains_all_steps():
    """T-EO-01: execution_order() lists every registered step."""
    assert set(execution_order()) == set(STEPS.keys())


def test_upload_before_column_types():
    """T-EO-02: upload < column_types (direct dependency)."""
    o = execution_order()
    assert _idx(o, "upload") < _idx(o, "column_types")


def test_upload_before_similarity():
    """T-EO-03: upload < similarity."""
    o = execution_order()
    assert _idx(o, "upload") < _idx(o, "similarity")


def test_column_types_before_pii():
    """T-EO-04: column_types < pii."""
    o = execution_order()
    assert _idx(o, "column_types") < _idx(o, "pii")


def test_pii_before_profiling():
    """T-EO-05: pii < profiling."""
    o = execution_order()
    assert _idx(o, "pii") < _idx(o, "profiling")


def test_etl_before_analysis():
    """T-EO-06: etl < analysis."""
    o = execution_order()
    assert _idx(o, "etl") < _idx(o, "analysis")


def test_analysis_before_dashboard():
    """T-EO-07: analysis < dashboard."""
    o = execution_order()
    assert _idx(o, "analysis") < _idx(o, "dashboard")


def test_dashboard_before_auditor():
    """T-EO-08: dashboard < auditor (after= constraint)."""
    o = execution_order()
    assert _idx(o, "dashboard") < _idx(o, "auditor")


def test_execution_order_idempotent():
    """T-EO-09: two calls return the same set."""
    assert set(execution_order()) == set(execution_order())
