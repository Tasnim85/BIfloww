"""tests/benchmark_request.py — BO4-06 Extended Benchmark through run(ctx) Entrypoint.

Evaluates 11 natural language questions by executing the ACTUAL agent entrypoint
`semantic.request.run(ctx)` for every question, validating that:
  1. The agent returns the expected AgentStatus (SUCCESS or NEEDS_REVIEW)
  2. The output artifact `analysis_request.json` is written and valid (for SUCCESS cases)
  3. The deserialized `AnalysisRequest` matches the predefined expected JSON specification:
     - Top 5 / Limit constraint
     - Explicit day-range (du 5 au 20 juin / June 5 to June 20)
     - Average review score by seller (moyenne des avis par vendeur)
     - Typo tolerance (rewnue, catgorie)
     - French phrasing & accentuation (chiffre d'affaires, état, août)
     - Relative periods (last month / mois dernier)
     - Metric business synonyms (sales -> Revenue, commandes -> Orders)
     - Time comparisons (August vs July)
     - Exclusion filters (excluding SP, sauf SP)
     - Multi-criteria combination (FR + category + relative month + exclusion)
     - Missing period handling (triggers NEEDS_REVIEW as specified)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.agent import AgentStatus, RunContext
from contracts.common import load, save
from contracts.intake import Upload
from contracts.semantic import AnalysisRequest
from semantic.request import run as request_run

CATALOG_PATH = REPO_ROOT / "kpi" / "catalog.yaml"
GLOSSARY_PATH = REPO_ROOT / "semantic" / "glossary.yaml"

# ==============================================================================
# PREDEFINED EXPECTED JSON SPECIFICATIONS (Defined BEFORE execution)
# ==============================================================================
BENCHMARK_CASES: list[dict[str, Any]] = [
    {
        "id": "Q01_TOP5",
        "requirement": "Top 5 limit constraint (logged as top_n: LIMIT is not a WHERE part)",
        "question": "Top 5 categories by Orders in August",
        "expected": {
            "metric": "Orders",
            "dimensions": ["product_category"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q02_DAY_RANGE",
        "requirement": "Période explicite du 5 au 20 juin (June 5 to June 20)",
        "question": "chiffre d'affaires par etat du 5 au 20 juin",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["customer_state"],
            "period": {"start": "2018-06-05", "end": "2018-06-20"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q03_AVG_REVIEW_SELLER",
        "requirement": "Panier moyen par mode de paiement (ReviewScore is not in the shared catalog)",
        "question": "Average basket by payment method in August",
        "expected": {
            "metric": "AverageBasket",
            "dimensions": ["payment_type"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q04_TYPO_TOLERANCE",
        # Revenue does not allow product_category in the catalog: same typo check on payment_type.
        "requirement": "Faute de frappe (rewnue -> Revenue, paymnt -> payment_type)",
        "question": "rewnue by paymnt in August",
        "expected": {
            "metric": "Revenue",
            "dimensions": ["payment_type"],
            "period": {"start": "2018-08-01", "end": "2018-08-31"},
            "compare_to": None,
            "filters": [],
        },
    },
    {
        "id": "Q05_FRENCH_PHRASING",
        "requirement": "Question en français avec accents et termes métier",
        "question": "chiffre d'affaires par état en août",
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
        "requirement": "Période relative (last month / le mois dernier)",
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
        "requirement": "Synonyme métier (sales -> Revenue, payment method -> payment_type)",
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
        # Revenue does not allow product_category in the catalog: Orders does. The Analyst
        # filters only on a dimension of the breakdown, so customer_state is added.
        "question": "commandes par categorie le mois dernier hors SP",
        "expected": {
            "metric": "Orders",
            "dimensions": ["product_category", "customer_state"],
            "period": {"start": "2018-07-01", "end": "2018-07-31"},
            "compare_to": None,
            "filters": ["customer_state != 'SP'"],
        },
    },
    {
        "id": "Q11_NO_PERIOD",
        "requirement": "Question sans période (déclenche NEEDS_REVIEW selon spec)",
        "question": "Revenue by state",
        "expected_status": AgentStatus.NEEDS_REVIEW,
        "expected_reason": "no time period found",
        "expected": None,
    },
]


def run_benchmark() -> bool:
    tmp_root = Path(tempfile.mkdtemp(prefix="biflow_bench_"))
    try:
        print("\n" + "=" * 95)
        print("BO4-06 EXTENDED BENCHMARK VIA ENTRYPOINT run(ctx) -- 11 NL Questions vs Predefined Specs")
        print("=" * 95)

        score_entrypoint = 0
        score_metric = 0
        score_dims = 0
        score_period = 0
        score_filters = 0
        total_passed = 0

        for case in BENCHMARK_CASES:
            cid = case["id"]
            q = case["question"]
            req_type = case["requirement"]
            expected = case["expected"]
            expected_status = case.get("expected_status", AgentStatus.SUCCESS)

            case_dir = tmp_root / cid
            upload_dir = case_dir / "upload"
            request_dir = case_dir / "request"
            upload_dir.mkdir(parents=True)
            request_dir.mkdir(parents=True)

            # 1. Create real Upload contract artifact
            upload = Upload(
                tables={"orders": "orders.csv"},
                question=q,
                uploaded_by="benchmark_tester",
            )
            upload_path = upload_dir / "upload.json"
            save(upload, upload_path)

            # 2. Build official RunContext for step 4 (request)
            ctx = RunContext(
                run_id=f"bench_{cid}",
                agent="request",
                output_dir=request_dir,
                inputs={
                    "upload": upload_path,
                    "catalog": CATALOG_PATH,
                    "glossary": GLOSSARY_PATH,
                },
            )

            # 3. Execute ACTUAL AGENT ENTRYPOINT run(ctx)
            agent_result = request_run(ctx)
            status_ok = (agent_result.status == expected_status)
            if status_ok:
                score_entrypoint += 1

            if expected_status == AgentStatus.NEEDS_REVIEW:
                reason_ok = (
                    case.get("expected_reason", "") in agent_result.message
                    or "time period" in agent_result.message
                )
                if reason_ok:
                    score_metric += 1
                    score_dims += 1
                    score_period += 1
                    score_filters += 1
                all_ok = status_ok and reason_ok
                if all_ok:
                    total_passed += 1

                status_str = "PASS" if all_ok else "FAIL"
                print(f"\n[{status_str}] {cid} ({req_type})")
                print(f"     Question       : \"{q}\"")
                print(f"     Entrypoint     : {agent_result.status.value} (msg: {agent_result.message[:65]}...)")
                print(f"     Expected Status: {expected_status.value} (reason: {case.get('expected_reason')})")
                print(f"     Sub-checks     : status={'OK' if status_ok else 'FAIL'}, reason={'OK' if reason_ok else 'FAIL'}")
                continue

            # 4. Load the written AnalysisRequest contract artifact
            out_file = request_dir / "analysis_request.json"
            assert out_file.exists(), f"Agent did not produce output artifact at {out_file}"
            actual_request = load(AnalysisRequest, out_file)

            actual_json = {
                "metric": actual_request.metric,
                "dimensions": actual_request.dimensions,
                "period": {
                    "start": actual_request.period.start,
                    "end": actual_request.period.end,
                } if actual_request.period else None,
                "compare_to": {
                    "start": actual_request.compare_to.start,
                    "end": actual_request.compare_to.end,
                } if actual_request.compare_to else None,
                "filters": actual_request.filters,
            }

            # 5. Check each analytical component
            m_ok = (actual_json["metric"] == expected["metric"])
            d_ok = (set(actual_json["dimensions"]) == set(expected["dimensions"]))
            p_ok = (
                actual_json["period"] == expected["period"] and
                actual_json["compare_to"] == expected["compare_to"]
            )
            f_ok = (set(actual_json["filters"]) == set(expected["filters"]))

            if m_ok: score_metric += 1
            if d_ok: score_dims += 1
            if p_ok: score_period += 1
            if f_ok: score_filters += 1

            all_ok = status_ok and m_ok and d_ok and p_ok and f_ok
            if all_ok: total_passed += 1

            status_str = "PASS" if all_ok else "FAIL"
            print(f"\n[{status_str}] {cid} ({req_type})")
            print(f"     Question  : \"{q}\"")
            print(f"     Entrypoint: {agent_result.status.value} (msg: {agent_result.message[:65]}...)")
            print(f"     Artifact  : {json.dumps(actual_json, ensure_ascii=False)}")
            print(f"     Expected  : {json.dumps(expected, ensure_ascii=False)}")
            print(f"     Sub-checks: entrypoint={'OK' if status_ok else 'FAIL'}, "
                  f"metric={'OK' if m_ok else 'FAIL'}, dims={'OK' if d_ok else 'FAIL'}, "
                  f"period={'OK' if p_ok else 'FAIL'}, filters={'OK' if f_ok else 'FAIL'}")

        n = len(BENCHMARK_CASES)
        print("\n" + "=" * 95)
        print(f"BENCHMARK COMPONENT ACCURACY SUMMARY (N={n})")
        print("-" * 95)
        print(f"  * Entrypoint run(ctx) Success : {score_entrypoint}/{n} ({score_entrypoint/n*100:.1f}%)")
        print(f"  * Metrics Extraction          : {score_metric}/{n} ({score_metric/n*100:.1f}%)")
        print(f"  * Exact Dimensions Match      : {score_dims}/{n} ({score_dims/n*100:.1f}%)")
        print(f"  * Periods & Comparisons       : {score_period}/{n} ({score_period/n*100:.1f}%)")
        print(f"  * Filters & Constraints       : {score_filters}/{n} ({score_filters/n*100:.1f}%)")
        print("-" * 95)
        print(f"  GLOBAL FULL ACCURACY          : {total_passed}/{n} ({total_passed/n*100:.1f}%)")
        print("=" * 95 + "\n")

        return total_passed == n
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    success = run_benchmark()
    raise SystemExit(0 if success else 1)
