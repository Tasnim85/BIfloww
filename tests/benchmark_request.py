"""tests/benchmark_request.py — BO4-06 Extended Benchmark.

Evaluates 10 natural language questions against predefined expected JSON specifications,
measuring each analytical component separately:
  1. Top 5 / Limit constraint
  2. Explicit day-range (du 5 au 20 juin / June 5 to June 20)
  3. Average review score by seller (moyenne des avis par vendeur)
  4. Typo tolerance (rewnue, catgorie)
  5. French phrasing & accentuation (chiffre d'affaires, état, août)
  6. Relative periods (last month / mois dernier)
  7. Metric business synonyms (sales -> Revenue, commandes -> Orders)
  8. Time comparisons (August vs July)
  9. Exclusion filters (excluding SP, sauf SP)
 10. Multi-criteria combination (FR + category + relative month + exclusion)
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.semantic import Glossary, KpiCatalog, load_yaml
from semantic.request import _find_dimensions, _find_filters, _find_metric, _find_period
CATALOG_PATH = REPO_ROOT / "kpi" / "catalog.yaml"
GLOSSARY_PATH = REPO_ROOT / "semantic" / "glossary.yaml"

# ==============================================================================
# PREDEFINED EXPECTED JSON SPECIFICATIONS (Defined BEFORE execution)
# ==============================================================================
BENCHMARK_CASES: list[dict[str, Any]] = [
    {
        "id": "Q01_TOP5",
        "requirement": "Top 5 limit constraint",
        "question": "Top 5 categories by Revenue in August",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["product_category"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": ["LIMIT 5"],
        },
    },
    {
        "id": "Q02_DATE_RANGE",
        "requirement": "Période explicite du 5 au 20 juin",
        "question": "Revenue by state from June 5 to June 20",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["customer_state"],
            "period": {"start": "2018-06-05", "end": "2018-06-20"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q03_REVIEW_SELLER",
        "requirement": "Moyenne des avis par vendeur",
        "question": "moyenne des avis par vendeur en aout",
        "expected": {
            "metric": "ReviewScore",
            "dimensions": ["seller_id"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q04_TYPO",
        "requirement": "Faute de frappe (rewnue, catgorie)",
        "question": "rewnue by catgorie in August",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["product_category"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q05_FRENCH",
        "requirement": "Question française complète",
        "question": "chiffre d'affaires par etat en aout",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["customer_state"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q06_RELATIVE_PERIOD",
        "requirement": "Période relative (last month)",
        "question": "Revenue by state last month",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["customer_state"],
            "period": {"start": "2018-07-01", "end": "2018-07-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q07_SYNONYM",
        "requirement": "Synonyme métier (sales -> Revenue)",
        "question": "sales by payment method in October",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["payment_type"],
            "period": {"start": "2018-10-01", "end": "2018-10-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q08_COMPARISON",
        "requirement": "Comparaison temporelle (August vs July)",
        "question": "Orders by category in August vs July",
        "expected": {
            "metric": "Orders",
            "dimensions": ["product_category"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": {"start": "2018-07-01", "end": "2018-07-31"},
            "filters": [],
        },
    },
    {
        "id": "Q09_EXCLUSION_FILTER",
        "requirement": "Filtre d'exclusion (excluding SP)",
        "question": "Revenue by state in August excluding SP",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["customer_state"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": ["customer_state != 'SP'"],
        },
    },
    {
        "id": "Q10_COMBO",
        "requirement": "Combinaison multiple (FR + catégorie + mois relatif + exclusion)",
        "question": "ventes par categorie le mois dernier hors SP",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["product_category"],
            "period": {"start": "2018-07-01", "end": "2018-07-31"},
            "compare_to": None,
            "filters": ["customer_state != 'SP'"],
        },
    },
]


def run_benchmark() -> bool:
    catalog = load_yaml(KpiCatalog, CATALOG_PATH)
    glossary = load_yaml(Glossary, GLOSSARY_PATH)

    print("\n" + "=" * 90)
    print("BO4-06 EXTENDED BENCHMARK -- 10 NL Questions vs Predefined Expected JSON Specs")
    print("=" * 90)

    score_metric = 0
    score_dims = 0
    score_period = 0
    score_filters = 0
    total_passed = 0

    results = []

    for case in BENCHMARK_CASES:
        cid = case["id"]
        q = case["question"]
        req_type = case["requirement"]
        expected = case["expected"]

        # Run extraction
        q_lower = q.lower()
        metric, conf = _find_metric(q_lower, catalog, glossary)
        dims = _find_dimensions(q_lower, catalog, glossary)
        period, compare_to = _find_period(q_lower)
        filters = _find_filters(q_lower, catalog)

        actual_json = {
            "metric": metric,
            "dimensions": dims,
            "period": {"start": period.start, "end": period.end} if period else None,
            "compare_to": {"start": compare_to.start, "end": compare_to.end} if compare_to else None,
            "filters": filters,
        }

        # Check each component
        m_ok = (actual_json["metric"] == expected["metric"])
        d_ok = (set(actual_json["dimensions"]) == set(expected["dimensions"]))
        p_ok = (actual_json["period"] == expected["period"] and actual_json["compare_to"] == expected["compare_to"])
        f_ok = (set(actual_json["filters"]) == set(expected["filters"]))

        if m_ok: score_metric += 1
        if d_ok: score_dims += 1
        if p_ok: score_period += 1
        if f_ok: score_filters += 1

        all_ok = m_ok and d_ok and p_ok and f_ok
        if all_ok: total_passed += 1

        status_str = "PASS" if all_ok else "FAIL"
        print(f"\n[{status_str}] {cid} ({req_type})")
        print(f"     Question  : \"{q}\"")
        print(f"     Extracted : {json.dumps(actual_json, ensure_ascii=False)}")
        print(f"     Expected  : {json.dumps(expected, ensure_ascii=False)}")
        print(f"     Sub-checks: metric={'OK' if m_ok else 'FAIL'}, dims={'OK' if d_ok else 'FAIL'}, "
              f"period={'OK' if p_ok else 'FAIL'}, filters={'OK' if f_ok else 'FAIL'}")

    n = len(BENCHMARK_CASES)
    print("\n" + "=" * 90)
    print(f"BENCHMARK COMPONENT ACCURACY SUMMARY (N={n})")
    print("-" * 90)
    print(f"  * Metrics Extraction    : {score_metric}/{n} ({score_metric/n*100:.1f}%)")
    print(f"  * Exact Dimensions Match: {score_dims}/{n} ({score_dims/n*100:.1f}%)")
    print(f"  * Periods & Comparisons : {score_period}/{n} ({score_period/n*100:.1f}%)")
    print(f"  * Filters & Constraints : {score_filters}/{n} ({score_filters/n*100:.1f}%)")
    print("-" * 90)
    print(f"  GLOBAL FULL ACCURACY    : {total_passed}/{n} ({total_passed/n*100:.1f}%)")
    print("=" * 90 + "\n")

    return total_passed == n


if __name__ == "__main__":
    success = run_benchmark()
    raise SystemExit(0 if success else 1)
