"""semantic/request.py -- Step 4: request understanding (Malek -- BO4-06).

Turns a user's natural-language question into a validated AnalysisRequest
by searching the business glossary with keyword matching.

Step 1 (this file): keyword matching against the glossary (no embeddings).
Step 2 (future):    sentence-embedding cosine search (Sentence-Transformers).

Fixes vs v1.0:
  - month-end computed with calendar.monthrange (no more hardcoded 31)
  - first month mentioned = main period; second = compare_to
    ("X vs Y", "compared to", "than", "versus" all handled correctly)
  - no silent fallback to first KPI -- returns NEEDS_REVIEW if metric not found
  - returns NEEDS_REVIEW if no month found in the question
  - date fields validated with datetime.date.fromisoformat()

Fixes vs v1.2 (2026-10-21 second-pass audit):
  - _find_metric now accepts an optional Glossary and resolves business
    synonyms before returning None:
      sales -> Revenue,  chiffre d'affaires -> Revenue,  ventes -> Revenue
      commandes -> Orders,  nombre de commandes -> Orders
  - _MONTH_MAP extended with French month names (janvier/aout/fevrier ...)
  - _find_dimensions extended with glossary dimension synonyms (etat, categorie ...)
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import Period, load, save
from contracts.intake import Upload
from contracts.semantic import AnalysisRequest, Glossary, KpiCatalog, load_yaml


def _normalize(text: str) -> str:
    """Lowercase + strip accents + normalise apostrophes.

    Handles:
      - Accented characters (aout == aout, fevrier == fevrier)
      - Unicode apostrophe variants (U+2019 RIGHT SINGLE QUOTATION MARK -> ')
    """
    # Replace curly / typographic apostrophes with straight single quote
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# Month name (EN + FR, with and without accents) -> zero-padded month number
_MONTH_MAP: dict[str, str] = {
    # English
    "january": "01", "february": "02", "march": "03",   "april": "04",
    "may":     "05", "june":     "06", "july":   "07",   "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    # French (accented forms pre-normalised so they always match even without accent)
    "janvier":   "01", "fevrier":  "02", "mars":      "03", "avril":    "04",
    "mai":       "05", "juin":     "06", "juillet":   "07", "aout":     "08",
    "septembre": "09", "octobre":  "10", "novembre":  "11", "decembre": "12",
}

# Comparison connectors -- the month AFTER these words is compare_to
_COMPARE_PATTERNS = re.compile(
    r"\b(?:vs\.?|versus|compared\s+to|than|against|par\s+rapport\s+a)\s+(\w+)",
    re.IGNORECASE,
)


def _find_metric(
    question_lower: str,
    catalog: KpiCatalog,
    glossary: Glossary | None = None,
) -> tuple[str | None, float]:
    """Return (metric_name, confidence) or (None, 0.0) if no match.

    Resolution order:
      1. Direct KPI name match           (conf 0.90)
      2. KPI name word-split token       (conf 0.60)
      3. Glossary synonym match          (conf 0.75)  -- NEW in v1.2
      4. Return (None, 0.0)
    """
    q = question_lower

    # Tier 1: exact KPI name in question
    for kpi in catalog.kpis:
        if kpi.name.lower() in q:
            return kpi.name, 0.90

    # Tier 2: KPI name word-split (e.g. "revenue" splits to ["revenue"])
    for kpi in catalog.kpis:
        for kw in kpi.name.lower().split("_"):
            if len(kw) > 3 and kw in q:
                return kpi.name, 0.60

    # Tier 3: glossary synonyms for metric terms
    if glossary is not None:
        kpi_names_lower = {kpi.name.lower(): kpi.name for kpi in catalog.kpis}
        q_norm = _normalize(q)
        for term in glossary.terms:
            if term.kind != "metric":
                continue
            candidates = [term.term.lower()] + [s.lower() for s in term.synonyms]
            for candidate in candidates:
                norm_cand = _normalize(candidate)
                # Use word-boundary matching to avoid "ca" matching inside "categorie"
                pattern = r"(?<![a-z0-9])" + re.escape(norm_cand) + r"(?![a-z0-9])"
                if re.search(pattern, q_norm):
                    for kpi_lower, kpi_name in kpi_names_lower.items():
                        if kpi_lower == term.term.lower() or term.term.lower() in kpi_lower:
                            return kpi_name, 0.75

    return None, 0.0


def _find_dimensions(
    question_lower: str,
    catalog: KpiCatalog,
    glossary: Glossary | None = None,
) -> list[str]:
    """Return catalog dimension names mentioned in the question.

    Checks dimension name, word-split tokens, and glossary synonyms (v1.2).
    """
    q_norm = _normalize(question_lower)
    found: list[str] = []
    dim_names = {dim.name for dim in catalog.dimensions}

    # Build synonym -> dim_name map from glossary
    syn_to_dim: dict[str, str] = {}
    if glossary is not None:
        for term in glossary.terms:
            if term.kind == "dimension" and term.term in dim_names:
                for syn in term.synonyms:
                    syn_to_dim[_normalize(syn)] = term.term

    for dim in catalog.dimensions:
        matched = False
        # Direct name or token match
        if dim.name.lower() in question_lower:
            matched = True
        elif any(kw in question_lower for kw in dim.name.lower().split("_")):
            matched = True
        # Glossary synonym match (normalised)
        elif any(
            syn in q_norm for syn in (
                syn_to_dim.keys()
                if syn_to_dim
                else []
            )
            if syn_to_dim.get(syn) == dim.name
        ):
            matched = True
        if matched:
            found.append(dim.name)

    return found[:3]


def _make_period(year: str, month: str) -> Period:
    """Build a Period for the given year/month, using calendar.monthrange for end-day."""
    y, m = int(year), int(month)
    last_day = calendar.monthrange(y, m)[1]
    start_str = f"{y:04d}-{m:02d}-01"
    end_str   = f"{y:04d}-{m:02d}-{last_day:02d}"
    date.fromisoformat(start_str)
    date.fromisoformat(end_str)
    return Period(start=start_str, end=end_str)


def _find_period(question_lower: str) -> tuple[Period | None, Period | None]:
    """Extract main period and optional comparison period from the question.

    Works on both raw and accent-stripped text (month names pre-normalised).
    """
    q_norm = _normalize(question_lower)

    year_match = re.search(r"\b(20\d{2})\b", q_norm)
    year = year_match.group(1) if year_match else "2018"  # Olist dataset default

    compare_months: set[str] = set()
    for m in _COMPARE_PATTERNS.finditer(q_norm):
        word = m.group(1).lower()
        word_norm = _normalize(word)
        if word_norm in _MONTH_MAP:
            compare_months.add(_MONTH_MAP[word_norm])

    mentioned: list[str] = []
    for name, num in _MONTH_MAP.items():
        if name in q_norm and num not in mentioned:
            mentioned.append(num)

    if not mentioned:
        return None, None

    main_month: str | None = None
    for num in mentioned:
        if num not in compare_months:
            main_month = num
            break
    if main_month is None:
        main_month = mentioned[0]

    compare_month: str | None = None
    for num in mentioned:
        if num != main_month:
            compare_month = num
            break

    period  = _make_period(year, main_month)
    compare = _make_period(year, compare_month) if compare_month else None
    return period, compare


def _match_terms(question_lower: str, glossary: Glossary) -> dict[str, str]:
    matched: dict[str, str] = {}
    q_norm = _normalize(question_lower)
    for term in glossary.terms:
        for syn in term.synonyms:
            if _normalize(syn) in q_norm:
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

    # Pass glossary into _find_metric so synonyms are resolved
    metric, confidence = _find_metric(q_lower, catalog, glossary)
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

    dimensions    = _find_dimensions(q_lower, catalog, glossary)
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
        rule_version="request:keyword@1.2",
        evidence={
            "metric": metric,
            "dimensions": dimensions,
            "confidence": confidence,
            "period": f"{period.start}...{period.end}",
            "compare_to": compare_to.model_dump() if compare_to else None,
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"request": out_path},
        message=(
            f"Parsed: metric={metric}, dims={dimensions}, "
            f"period={period.start}...{period.end}, confidence={confidence:.0%}"
        ),
    )
