"""benchmark_request.py -- BO4-06 Benchmark: NL question -> AnalysisRequest.

Tests 10 representative questions against the real catalog and glossary.
Measures: correct metric, correct dimensions, correct period, comparison detection,
and matches against predefined expected JSON representations.

Run standalone: python tests/benchmark_request.py
Run via pytest:  python -m pytest tests/benchmark_request.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.semantic import Glossary, KpiCatalog
from semantic.request import _find_dimensions, _find_metric, _find_period

CATALOG_PATH = REPO_ROOT / "kpi" / "catalog.yaml"
GLOSSARY_PATH = REPO_ROOT / "semantic" / "glossary.yaml"


def load_catalog() -> KpiCatalog:
    import yaml
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    return KpiCatalog.model_validate(data)


def load_glossary() -> Glossary:
    import yaml
    data = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return Glossary.model_validate(data)


# ---------------------------------------------------------------------------
# Predefined Expected JSON specifications (defined before execution)
# ---------------------------------------------------------------------------
EXPECTED_SPECS = [
    {
        "id": "Q01",
        "question": "Revenue by state in August vs July",
        "expected": {
            "metric": "Revenue",
            "dims_contain": ["customer_state"],
            "period_month": "08",
            "compare_month": "07",
        },
    },
    {
        "id": "Q02",
        "question": "Orders by category in September",
        "expected": {
            "metric": "Orders",
            "dims_contain": ["product_category"],
            "period_month": "09",
            "compare_month": None,
        },
    },
    {
        "id": "Q03",
        "question": "Revenue by payment type in October",
        "expected": {
            "metric": "Revenue",
            "dims_contain": ["payment_type"],
            "period_month": "10",
            "compare_month": None,
        },
    },
    {
        "id": "Q04",
        "question": "Revenue in August",
        "expected": {
            "metric": "Revenue",
            "dims_contain": [],
            "period_month": "08",
            "compare_month": None,
        },
    },
    {
        "id": "Q05",
        "question": "sales by state in August",
        "expected": {
            "metric": "Revenue",
            "dims_contain": ["customer_state"],
            "period_month": "08",
            "compare_month": None,
        },
    },
    {
        "id": "Q06",
        "question": "chiffre d'affaires par etat en aout",
        "expected": {
            "metric": "Revenue",
            "dims_contain": ["customer_state"],
            "period_month": "08",
            "compare_month": None,
        },
    },
    {
        "id": "Q07",
        "question": "Revenue by state",
        "expected": {
            "metric": "Revenue",
            "dims_contain": ["customer_state"],
            "period_month": None,
            "compare_month": None,
        },
    },
    {
        "id": "Q08",
        "question": "Revenue by state in August 2017",
        "expected": {
            "metric": "Revenue",
            "dims_contain": ["customer_state"],
            "period_month": "08",
            "period_year": "2017",
            "compare_month": None,
        },
    },
    {
        "id": "Q09",
        "question": "orders by seller state in July vs June",
        "expected": {
            "metric": "Orders",
            "dims_contain": ["seller_state"],
            "period_month": "07",
            "compare_month": "06",
        },
    },
    {
        "id": "Q10",
        "question": "number of orders in august",
        "expected": {
            "metric": "Orders",
            "dims_contain": [],
            "period_month": "08",
            "compare_month": None,
        },
    },
]


def run_benchmark() -> tuple[int, int]:
    """Run all 10 cases with catalog & glossary, checking against expected specs."""
    catalog = load_catalog()
    glossary = load_glossary()

    results: list[str] = []
    score_metric = score_dims = score_period = score_compare = 0
    total = len(EXPECTED_SPECS)

    print(f"\n{'='*72}")
    print("BO4-06 BENCHMARK -- 10 NL questions -> AnalysisRequest components")
    print(f"Catalog  : {CATALOG_PATH.name} ({len(catalog.kpis)} KPIs, {len(catalog.dimensions)} dims)")
    print(f"Glossary : {GLOSSARY_PATH.name} ({len(glossary.terms)} terms)")
    print(f"{'='*72}\n")

    for item in EXPECTED_SPECS:
        qid = item["id"]
        question = item["question"]
        exp = item["expected"]

        q = question.lower()
        metric, conf = _find_metric(q, catalog, glossary)
        dims = _find_dimensions(q, catalog, glossary)
        period, compare_to = _find_period(q)

        m_ok = metric == exp["metric"]
        d_ok = all(d in dims for d in exp["dims_contain"])

        if exp["period_month"] is None:
            p_ok = period is None
        else:
            p_ok = (
                period is not None
                and period.start[5:7] == exp["period_month"]
                and (exp.get("period_year") is None or period.start[:4] == exp["period_year"])
            )

        if exp["compare_month"] is None:
            c_ok = compare_to is None
        else:
            c_ok = (compare_to is not None and compare_to.start[5:7] == exp["compare_month"])

        if m_ok: score_metric += 1
        if d_ok: score_dims += 1
        if p_ok: score_period += 1
        if c_ok: score_compare += 1

        all_ok = m_ok and d_ok and p_ok and c_ok
        status = "PASS" if all_ok else "FAIL"
        results.append(status)

        extracted_json = {
            "metric": metric,
            "confidence": conf,
            "dimensions": dims,
            "period": f"{period.start}..{period.end}" if period else None,
            "compare_to": f"{compare_to.start}..{compare_to.end}" if compare_to else None,
        }

        print(f"{qid} [{status}] {question!r}")
        print(f"     Extracted: {json.dumps(extracted_json)}")
        print(f"     Expected : {json.dumps(exp)}")
        print(f"     Checks   : metric={'OK' if m_ok else 'MISS'}, dims={'OK' if d_ok else 'MISS'}, "
              f"period={'OK' if p_ok else 'MISS'}, compare={'OK' if c_ok else 'MISS'}")
        print()

    passed = results.count("PASS")
    print(f"{'='*72}")
    print(f"SCORE  : {passed}/{total} questions fully correct ({passed/total*100:.0f}%)")
    print(f"  Metric     : {score_metric}/{total}")
    print(f"  Dimensions : {score_dims}/{total}")
    print(f"  Period     : {score_period}/{total}")
    print(f"  Comparison : {score_compare}/{total}")
    print(f"{'='*72}\n")

    return passed, total


# ---------------------------------------------------------------------------
# pytest entry points
# ---------------------------------------------------------------------------

def test_benchmark_all_10_pass():
    """T-BM-01: 10/10 questions fully correct with glossary synonym resolution."""
    passed, total = run_benchmark()
    assert passed == 10, f"Expected 10/10, got {passed}/{total}"


def test_find_metric_revenue():
    """T-BM-02: 'revenue ...' -> metric=Revenue."""
    catalog = load_catalog()
    glossary = load_glossary()
    metric, conf = _find_metric("revenue by state in august", catalog, glossary)
    assert metric == "Revenue"
    assert conf >= 0.9


def test_find_metric_orders():
    """T-BM-03: 'orders ...' -> metric=Orders."""
    catalog = load_catalog()
    glossary = load_glossary()
    metric, conf = _find_metric("orders by category in september", catalog, glossary)
    assert metric == "Orders"


def test_find_metric_unknown_returns_none():
    """T-BM-04: no matching KPI -> (None, 0.0)."""
    catalog = load_catalog()
    glossary = load_glossary()
    metric, conf = _find_metric("what is the weather today", catalog, glossary)
    assert metric is None
    assert conf == 0.0


def test_find_dimensions_customer_state():
    """T-BM-05: 'state' in question -> customer_state in dims."""
    catalog = load_catalog()
    glossary = load_glossary()
    dims = _find_dimensions("revenue by state in august", catalog, glossary)
    assert "customer_state" in dims


def test_find_dimensions_product_category():
    """T-BM-06: 'category' in question -> product_category in dims."""
    catalog = load_catalog()
    glossary = load_glossary()
    dims = _find_dimensions("orders by category", catalog, glossary)
    assert "product_category" in dims


def test_find_period_august():
    """T-BM-07: 'august' -> period.start starts with some year-08."""
    period, compare = _find_period("revenue by state in august")
    assert period is not None
    assert "-08-" in period.start
    assert compare is None


def test_find_period_comparison():
    """T-BM-08: 'august vs july' -> period=Aug, compare=Jul."""
    period, compare = _find_period("revenue in august vs july")
    assert period is not None and "-08-" in period.start
    assert compare is not None and "-07-" in compare.start


def test_find_period_no_month():
    """T-BM-09: question without month -> (None, None)."""
    period, compare = _find_period("revenue by state")
    assert period is None
    assert compare is None


def test_find_period_with_explicit_year():
    """T-BM-10: '2017' in question -> period year=2017."""
    period, _ = _find_period("revenue by state in august 2017")
    assert period is not None
    assert period.start.startswith("2017-")


if __name__ == "__main__":
    run_benchmark()
