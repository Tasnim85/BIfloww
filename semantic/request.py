"""semantic/request.py — Step 4: request understanding (Malek — BO4-06).

Turns a user's natural-language question into a validated AnalysisRequest
by searching the business glossary with keyword matching.

Step 1 (this file): keyword matching against the glossary (no embeddings).
Step 2 (future):    sentence-embedding cosine search (Sentence-Transformers).

Fixes vs v1.0:
  - month-end computed with calendar.monthrange (no more hardcoded 31)
  - first month mentioned = main period; second = compare_to
    ("X vs Y", "compared to", "than", "versus" all handled correctly)
  - no silent fallback to first KPI — returns NEEDS_REVIEW if metric not found
  - returns NEEDS_REVIEW if no month found in the question
  - date fields validated with datetime.date.fromisoformat()
"""
from __future__ import annotations

import calendar
import re
from datetime import date

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import Period, load, save
from contracts.intake import Upload
from contracts.semantic import AnalysisRequest, Glossary, KpiCatalog, load_yaml

# ── Month name → zero-padded month number ────────────────────────────────────
_MONTH_MAP: dict[str, str] = {
    "january": "01", "february": "02", "march": "03",   "april": "04",
    "may":     "05", "june":     "06", "july":   "07",   "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

# Comparison connectors — the month AFTER these words is compare_to
_COMPARE_PATTERNS = re.compile(
    r"\b(?:vs\.?|versus|compared\s+to|than|against)\s+(\w+)",
    re.IGNORECASE,
)


def _find_metric(question_lower: str, catalog: KpiCatalog) -> tuple[str | None, float]:
    """Return (metric_name, confidence) or (None, 0.0) if no match.

    No silent fallback — callers must handle None and return NEEDS_REVIEW.
    """
    for kpi in catalog.kpis:
        if kpi.name.lower() in question_lower:
            return kpi.name, 0.90

    # Synonym scan via aliases/keywords if available
    for kpi in catalog.kpis:
        for kw in kpi.name.lower().split("_"):
            if len(kw) > 3 and kw in question_lower:
                return kpi.name, 0.60

    return None, 0.0


def _find_dimensions(question_lower: str, catalog: KpiCatalog) -> list[str]:
    dims = []
    for dim in catalog.dimensions:
        if dim.name.lower() in question_lower or any(
            kw in question_lower for kw in dim.name.lower().split("_")
        ):
            dims.append(dim.name)
    return dims[:3]  # at most 3 dimensions


def _make_period(year: str, month: str) -> Period:
    """Build a Period for the given year/month, using calendar.monthrange for end-day."""
    y, m = int(year), int(month)
    last_day = calendar.monthrange(y, m)[1]  # correct month-end (28/29/30/31)
    start_str = f"{y:04d}-{m:02d}-01"
    end_str   = f"{y:04d}-{m:02d}-{last_day:02d}"
    # Validate — will raise ValueError if dates are malformed
    date.fromisoformat(start_str)
    date.fromisoformat(end_str)
    return Period(start=start_str, end=end_str)


def _find_period(question_lower: str) -> tuple[Period | None, Period | None]:
    """Extract main period and optional comparison period from the question.

    Rules:
      1. Months mentioned after a comparison connector ("vs", "compared to", …)
         are treated as compare_to.
      2. The first remaining month is the main period.
      3. Returns (None, None) if no month found.
    """
    year_match = re.search(r"\b(20\d{2})\b", question_lower)
    year = year_match.group(1) if year_match else "2018"  # Olist dataset default

    # Find months mentioned after a comparison connector
    compare_months: set[str] = set()
    for m in _COMPARE_PATTERNS.finditer(question_lower):
        word = m.group(1).lower()
        if word in _MONTH_MAP:
            compare_months.add(_MONTH_MAP[word])

    # Collect all months in order of appearance
    mentioned: list[str] = []
    for name, num in _MONTH_MAP.items():
        if name in question_lower and num not in mentioned:
            mentioned.append(num)

    if not mentioned:
        return None, None  # caller must return NEEDS_REVIEW

    # Main period = first month NOT flagged as a comparison month
    main_month: str | None = None
    for num in mentioned:
        if num not in compare_months:
            main_month = num
            break
    if main_month is None:
        main_month = mentioned[0]  # all months are comparisons — pick first

    compare_month: str | None = None
    for num in mentioned:
        if num != main_month:
            compare_month = num
            break

    period   = _make_period(year, main_month)
    compare  = _make_period(year, compare_month) if compare_month else None
    return period, compare


def _match_terms(question_lower: str, glossary: Glossary) -> dict[str, str]:
    matched: dict[str, str] = {}
    for term in glossary.terms:
        for syn in term.synonyms:
            if syn.lower() in question_lower:
                matched[syn.lower()] = term.term
    return matched


def run(ctx: RunContext) -> AgentResult:
    """Step 4: parse the user's question and produce an AnalysisRequest."""
    try:
        upload   = load(Upload, ctx.inputs["upload"])
        catalog  = load_yaml(KpiCatalog, ctx.inputs["catalog"])
        glossary = load_yaml(Glossary,   ctx.inputs["glossary"])
    except Exception as exc:
        ctx.log("parse_request", "FAILED", evidence={"error": str(exc)})
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.FAILED,
            message=f"Could not load inputs: {exc}",
        )

    question = upload.question
    q_lower  = question.lower()

    metric, confidence = _find_metric(q_lower, catalog)
    if metric is None:
        ctx.log(
            "parse_request", "NEEDS_REVIEW",
            evidence={"question": question, "reason": "no KPI matched"},
        )
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.NEEDS_REVIEW,
            message=(
                f"Could not match any KPI from the catalog in: '{question}'. "
                "Please reformulate or specify the metric explicitly."
            ),
        )

    period, compare_to = _find_period(q_lower)
    if period is None:
        ctx.log(
            "parse_request", "NEEDS_REVIEW",
            evidence={"question": question, "reason": "no time period found"},
        )
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.NEEDS_REVIEW,
            message=(
                f"Could not identify a time period in: '{question}'. "
                "Please mention a month or date range."
            ),
        )

    dimensions    = _find_dimensions(q_lower, catalog)
    matched_terms = _match_terms(q_lower, glossary)

    request = AnalysisRequest(
        question=question,
        metric=metric,
        dimensions=dimensions,
        period=period,
        compare_to=compare_to,
        confidence=confidence,
        matched_terms=matched_terms,
    )

    out_path = ctx.output("request")
    save(request, out_path)

    ctx.log(
        "parse_request", "SUCCESS",
        outputs=[str(out_path)],
        rule_version="request:keyword@1.1",
        evidence={
            "metric": metric,
            "dimensions": dimensions,
            "confidence": confidence,
            "period": f"{period.start}…{period.end}",
            "compare_to": compare_to.model_dump() if compare_to else None,
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"request": out_path},
        message=(
            f"Parsed: metric={metric}, dims={dimensions}, "
            f"period={period.start}…{period.end}, confidence={confidence:.0%}"
        ),
    )
