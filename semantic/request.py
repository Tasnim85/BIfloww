"""semantic/request.py — Step 4: request understanding (Malek — BO4-06).

Turns a user's natural-language question into a validated AnalysisRequest
by searching the business glossary with embeddings.

Step 1 (this file): keyword matching against the glossary (no embeddings).
Step 2 (future):    sentence-embedding cosine search (Sentence-Transformers).
"""
from __future__ import annotations

from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import Period, load, save
from contracts.intake import Upload
from contracts.semantic import AnalysisRequest, Glossary, KpiCatalog, load_yaml


# ── Simple keyword matcher (Phase 1 — no embeddings) ─────────────────────
def _find_metric(question_lower: str, catalog: KpiCatalog) -> tuple[str, float]:
    """Return (metric_name, confidence) — first keyword match wins."""
    for kpi in catalog.kpis:
        if kpi.name.lower() in question_lower:
            return kpi.name, 0.90

    # Synonym scan via glossary terms
    return catalog.kpis[0].name if catalog.kpis else "Revenue", 0.50


def _find_dimensions(question_lower: str, catalog: KpiCatalog) -> list[str]:
    dims = []
    for dim in catalog.dimensions:
        if dim.name.lower() in question_lower or any(
            kw in question_lower for kw in dim.name.lower().split("_")
        ):
            dims.append(dim.name)
    return dims[:3]  # at most 3 dimensions


def _find_period(question_lower: str) -> tuple[Period, Period | None]:
    """Very light period extraction. Step 2 will use an LLM."""
    import re
    month_map = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
    }
    year = "2018"  # Olist dataset year
    main_month = "08"
    compare_month = None

    for name, num in month_map.items():
        if name in question_lower:
            if compare_month is None and main_month != num:
                compare_month = main_month
                main_month = num
            elif compare_month is None:
                compare_month = num

    m = re.search(r"\b(20\d{2})\b", question_lower)
    if m:
        year = m.group(1)

    period = Period(start=f"{year}-{main_month}-01", end=f"{year}-{main_month}-31")
    compare = (
        Period(start=f"{year}-{compare_month}-01", end=f"{year}-{compare_month}-31")
        if compare_month else None
    )
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
    dimensions         = _find_dimensions(q_lower, catalog)
    period, compare_to = _find_period(q_lower)
    matched_terms      = _match_terms(q_lower, glossary)

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
        rule_version="request:keyword@1.0",
        evidence={
            "metric": metric,
            "dimensions": dimensions,
            "confidence": confidence,
            "compare_to": compare_to.model_dump() if compare_to else None,
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"request": out_path},
        message=(f"Parsed: metric={metric}, dims={dimensions}, "
                 f"period={period.start}→{period.end}, confidence={confidence:.0%}"),
    )
