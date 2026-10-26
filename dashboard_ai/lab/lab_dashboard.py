"""Lab -- intelligent dashboard (BO4 step 6): chart choice + misleading-comparison detection.

Runs 9 scenarios on synthetic Olist-like data (no warehouse, no Ollama, no Streamlit needed):

    python -m dashboard_ai.lab.lab_dashboard                 # all scenarios, English
    python -m dashboard_ai.lab.lab_dashboard --lang fr       # messages in French
    python -m dashboard_ai.lab.lab_dashboard --only pie_27   # one scenario
    python -m dashboard_ai.lab.lab_dashboard --out /tmp/lab  # where PNG + CSV go

Each scenario prints: the question, the chart chosen, the ranking of every type with the
reason it was kept or rejected, and the visual warnings. PNGs show what the user would see.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.analysis import AnalysisResult
from contracts.common import Period
from contracts.comparisons import (CheckKind, CheckStatus, ComparisonCheck, ComparisonReport, FixMethod,
                                   ProposedFix, UserDecision)
from contracts.semantic import AnalysisRequest
from dashboard_ai.agent import build_dashboard
from dashboard_ai.misleading import mixed_units
from dashboard_ai.render import figure

AUG = Period(start="2018-08-01", end="2018-08-31")
JUL = Period(start="2018-07-01", end="2018-07-31")
SUM_SQL = "SELECT SUM(payment_value) AS value FROM fact_payments"
DISTINCT_SQL = "SELECT COUNT(DISTINCT customer_id) AS value FROM fact_payments"
UF = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "ES", "PE", "CE", "PA", "MT", "MS", "MA", "PB", "RN",
      "AL", "PI", "SE", "TO", "RO", "AM", "AC", "AP", "RR"]


@dataclass
class Scenario:
    name: str
    question: str
    dims: list[str]
    df: pd.DataFrame
    sql: str = SUM_SQL
    compare: bool = False
    value_current: float = 0.0
    value_previous: float | None = None
    report: ComparisonReport | None = None
    lesson: str = ""
    metric: str = "Revenue"


def _states(seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    weights = np.sort(rng.pareto(1.6, len(UF)) + 0.3)[::-1]
    return pd.DataFrame({"customer_state": UF, "value": (weights / weights.sum() * 1_000_000).round(2)})


def _compare_df() -> pd.DataFrame:
    s = _states()
    cur = s.assign(period="current")
    prev = s.assign(period="previous", value=(s["value"] * np.linspace(1.15, 0.7, len(s))).round(2))
    return pd.concat([cur, prev], ignore_index=True)


def scenarios() -> list[Scenario]:
    months = [f"2018-{m:02d}" for m in range(1, 9)]
    trend = pd.DataFrame({"order_month": months, "value": [90, 98, 110, 105, 120, 131, 128, 140.0]})
    gap = trend[~trend.order_month.isin(["2018-04", "2018-05"])].reset_index(drop=True)
    pay = pd.DataFrame({"payment_type": ["credit_card", "boleto", "voucher", "debit_card"], "value": [760.0, 190, 35, 15]})
    blocked = ComparisonReport(
        has_comparison=True, user_decision=UserDecision.PENDING,
        checks=[ComparisonCheck(kind=CheckKind.COVERAGE, status=CheckStatus.BLOCKING,
                                message="August has incomplete days from the 24th (volume < 60% of usual).")],
        proposed_fix=ProposedFix(method=FixMethod.SAME_DAYS, description="Compare 1-23 August with 1-23 July",
                                 justification="from the 24th the volume drops", period=AUG, compare_to=JUL,
                                 value_current=985_414.28, value_previous=732_000.0, change_pct=0.346))
    return [
        Scenario("kpi_total", "What is the total revenue in August 2018?", [], pd.DataFrame({"value": [1_027_903.86]}),
                 value_current=1_027_903.86, lesson="No dimension -> one number, no chart."),
        Scenario("bar_27", "Revenue by state", ["customer_state"], _states(), value_current=1_000_000.0,
                 lesson="27 categories -> top 15 + 'Others', sorted, axis from zero."),
        Scenario("pie_share", "Revenue share by payment type", ["payment_type"], pay, value_current=1000.0,
                 lesson="Share of a whole, 4 slices, additive KPI -> pie is allowed and chosen."),
        Scenario("pie_27", "Revenue by state as a pie chart", ["customer_state"], _states(), value_current=1_000_000.0,
                 lesson="The user asked for a pie: refused (27 slices), a bar is drawn with the reason."),
        Scenario("pie_distinct", "Customers by payment type as a pie chart", ["payment_type"],
                 pd.DataFrame({"payment_type": ["card", "boleto", "voucher"], "value": [600.0, 300, 150]}),
                 sql=DISTINCT_SQL, value_current=900.0, metric="Customers",
                 lesson="Distinct counts do not add up (a customer can use 2 payment types): pie refused."),
        Scenario("line_trend", "Evolution of revenue per month", ["order_month"], trend, value_current=923.0,
                 lesson="Time axis, 8 points -> line."),
        Scenario("line_gap", "Evolution of revenue per month", ["order_month"], gap, value_current=923.0,
                 lesson="Two months missing: a line would join across the hole, so it is flagged."),
        Scenario("cmp_blocked", "Revenue by customer state, August 2018 vs July 2018", ["customer_state"], _compare_df(),
                 compare=True, value_current=1_027_903.86, value_previous=1_072_000.0, report=blocked,
                 lesson="Real case of INTEGRATION.md: -4.1% asked, +34.6% on the same days. Comparison held back."),
        Scenario("base_effect", "Revenue August vs July", [], pd.DataFrame({"period": ["current", "previous"],
                 "value": [52_000.0, 800.0]}), compare=True, value_current=52_000.0, value_previous=800.0,
                 report=ComparisonReport(has_comparison=True), lesson="+6400% from a tiny base is not a performance."),
    ]


def run_scenario(s: Scenario, lang: str):
    req = AnalysisRequest(question=s.question, metric=s.metric, dimensions=s.dims, period=AUG,
                          compare_to=JUL if s.compare else None)
    chg = (s.value_current - s.value_previous) / s.value_previous if s.value_previous else None
    res = AnalysisResult(request=req, kpi="Revenue@2.0", sql=s.sql, rows=len(s.df), value_current=s.value_current,
                         value_previous=s.value_previous, change_pct=chg, unit="BRL", validations=[])
    return build_dashboard(req, res, s.report, s.df, lang=lang, data_dir=".")


def describe(s: Scenario, spec, advice) -> str:
    main = advice.decisions[-1]
    lines = [f"\n=== {s.name} ===", f"Question : {s.question}", f"Lesson   : {s.lesson}",
             f"Chosen   : {main.chosen.value}   (intent={main.intent}, requested={main.requested.value if main.requested else '-'},"
             f" comparison_shown={advice.comparison_shown})", "Ranking  :"]
    for c in main.candidates:
        mark = "OK " if c.eligible else "no "
        lines.append(f"   {mark}{c.chart_type.value:<9}{c.score:>5.0f}  {' | '.join(c.reasons)[:130]}")
    for w in spec.warnings:
        lines.append(f"   ! {w}")
    return "\n".join(lines)


def main() -> None:
    import matplotlib
    matplotlib.use("Agg")                      # CLI: draw to files only, no window
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default="en", choices=["en", "fr"])
    ap.add_argument("--only", default=None)
    ap.add_argument("--out", default="dashboard_ai/lab/out")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for s in scenarios():
        if args.only and s.name != args.only:
            continue
        spec, advice, frames = run_scenario(s, args.lang)
        print(describe(s, spec, advice))
        fig = figure(spec.charts, frames, spec.warnings)
        fig.savefig(out / f"{s.name}.png", dpi=110)
        main_d = advice.decisions[-1]
        rows.append({"scenario": s.name, "question": s.question, "chosen": main_d.chosen.value,
                     "requested": main_d.requested.value if main_d.requested else "", "issues": len(spec.warnings)})
    pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)

    if not args.only:
        issue = mixed_units({"Revenue": "BRL", "Orders": "orders", "Freight": "BRL"}, args.lang)
        print("\n=== multi_kpi_units ===\n   ! " + issue.message)
    print(f"\nPNG + summary.csv written to {out.resolve()}")


if __name__ == "__main__":
    main()
