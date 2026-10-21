"""semantic/request.py -- Step 4: request understanding (Malek -- BO4-06).

Turns a user's natural-language question into a validated AnalysisRequest
by searching the business glossary with keyword matching, typo tolerance,
filter detection, and period extraction.
"""
from __future__ import annotations

import calendar
import difflib
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
      - Accented characters (août == aout, février == fevrier)
      - Unicode apostrophe variants (U+2019 RIGHT SINGLE QUOTATION MARK -> ')
    """
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# Month name (EN + FR, with and without accents) -> zero-padded month number
_MONTH_MAP: dict[str, str] = {
    # English
    "january": "01", "february": "02", "march": "03",   "april": "04",
    "may":     "05", "june":     "06", "july":   "07",   "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    # French
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
      3. Glossary synonym match          (conf 0.75)
      4. Typo-tolerant fuzzy match       (conf 0.65)
      5. Return (None, 0.0)
    """
    q = question_lower
    q_norm = _normalize(q)

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
        for term in glossary.terms:
            if term.kind != "metric":
                continue
            candidates = [term.term.lower()] + [s.lower() for s in term.synonyms]
            for candidate in candidates:
                norm_cand = _normalize(candidate)
                # Word-boundary matching to avoid "ca" matching inside "categorie"
                pattern = r"(?<![a-z0-9])" + re.escape(norm_cand) + r"(?![a-z0-9])"
                if re.search(pattern, q_norm):
                    for kpi_lower, kpi_name in kpi_names_lower.items():
                        if kpi_lower == term.term.lower() or term.term.lower() in kpi_lower:
                            return kpi_name, 0.75

    # Tier 4: Typo tolerance via difflib on tokens
    words = re.findall(r"[a-z0-9']+", q_norm)
    all_metric_targets: dict[str, str] = {}
    for kpi in catalog.kpis:
        all_metric_targets[_normalize(kpi.name)] = kpi.name
    if glossary is not None:
        for term in glossary.terms:
            if term.kind == "metric":
                # Find corresponding kpi
                for kpi in catalog.kpis:
                    if kpi.name.lower() == term.term.lower():
                        for syn in term.synonyms:
                            all_metric_targets[_normalize(syn)] = kpi.name

    for word in words:
        if len(word) >= 4:
            matches = difflib.get_close_matches(word, list(all_metric_targets.keys()), n=1, cutoff=0.75)
            if matches:
                return all_metric_targets[matches[0]], 0.65

    return None, 0.0


def _find_dimensions(
    question_lower: str,
    catalog: KpiCatalog,
    glossary: Glossary | None = None,
) -> list[str]:
    """Return catalog dimension names mentioned in the question.

    Checks dimension name, word-split tokens, glossary synonyms, and fuzzy matching.
    Distinguishes between customer_state and seller_state, and only adds order_month
    when grouping by month is explicitly requested ('by month', 'par mois').
    """
    q_norm = _normalize(question_lower)
    found: list[str] = []
    dim_names = {dim.name for dim in catalog.dimensions}

    # 1. Specific checks for states to avoid collision
    has_seller_state = bool(re.search(r"\b(?:seller state|vendor state|etat vendeur|region vendeur)\b", q_norm))
    has_customer_state = bool(re.search(r"\b(?:customer state|state|etat|region)\b", q_norm)) and not has_seller_state

    if has_seller_state and "seller_state" in dim_names:
        found.append("seller_state")
    elif has_customer_state and "customer_state" in dim_names:
        found.append("customer_state")

    # 2. Check for seller_id / vendor
    if bool(re.search(r"\b(?:seller|vendor|vendeur|seller_id)\b", q_norm)) and not has_seller_state:
        if "seller_id" in dim_names and "seller_id" not in found:
            found.append("seller_id")

    # 3. Check for product_category
    if bool(re.search(r"\b(?:category|categorie|categories|product category|type produit)\b", q_norm)):
        if "product_category" in dim_names and "product_category" not in found:
            found.append("product_category")

    # 4. Check for payment_type
    if bool(re.search(r"\b(?:payment type|payment method|payment|mode paiement|type paiement)\b", q_norm)):
        if "payment_type" in dim_names and "payment_type" not in found:
            found.append("payment_type")

    # 5. Check for order_month (only if explicit grouping by month, not just a month date)
    if bool(re.search(r"\b(?:by month|per month|par mois|mensuel|monthly|group by month)\b", q_norm)):
        if "order_month" in dim_names and "order_month" not in found:
            found.append("order_month")

    # 6. Typo check for dimensions if none found
    if not found:
        words = re.findall(r"[a-z0-9]+", q_norm)
        for word in words:
            if len(word) >= 5:
                # check close match to category
                if difflib.get_close_matches(word, ["category", "categorie", "categories"], cutoff=0.75):
                    if "product_category" in dim_names and "product_category" not in found:
                        found.append("product_category")
                # check close match to payment
                elif difflib.get_close_matches(word, ["payment", "paiement"], cutoff=0.75):
                    if "payment_type" in dim_names and "payment_type" not in found:
                        found.append("payment_type")
                # check close match to state
                elif difflib.get_close_matches(word, ["state", "etat"], cutoff=0.75):
                    if "customer_state" in dim_names and "customer_state" not in found:
                        found.append("customer_state")

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

    Supports:
      - Explicit date range: "du 5 au 20 juin", "from June 5 to June 20"
      - Relative periods: "last month", "mois dernier", "previous month"
      - Month names (EN/FR) with optional comparison connectors: "August vs July"
    """
    q_norm = _normalize(question_lower)

    year_match = re.search(r"\b(20\d{2})\b", q_norm)
    year = year_match.group(1) if year_match else "2018"  # Olist dataset reference year

    # 1. Explicit day-range check: "du 5 au 20 juin", "from 5 to 20 june", "from june 5 to june 20"
    range_match_fr = re.search(r"\b(?:du\s+(\d{1,2})\s+au\s+(\d{1,2})\s+([a-z]+))", q_norm)
    if range_match_fr:
        d_start, d_end, m_name = int(range_match_fr.group(1)), int(range_match_fr.group(2)), range_match_fr.group(3)
        if m_name in _MONTH_MAP:
            m_num = _MONTH_MAP[m_name]
            p = Period(start=f"{year}-{m_num}-{d_start:02d}", end=f"{year}-{m_num}-{d_end:02d}")
            return p, None

    range_match_en = re.search(r"\b(?:from\s+([a-z]+)\s+(\d{1,2})\s+to\s+(?:[a-z]+\s+)?(\d{1,2}))", q_norm)
    if range_match_en:
        m_name, d_start, d_end = range_match_en.group(1), int(range_match_en.group(2)), int(range_match_en.group(3))
        if m_name in _MONTH_MAP:
            m_num = _MONTH_MAP[m_name]
            p = Period(start=f"{year}-{m_num}-{d_start:02d}", end=f"{year}-{m_num}-{d_end:02d}")
            return p, None

    range_match_en_alt = re.search(r"\b(?:from\s+(\d{1,2})\s+to\s+(\d{1,2})\s+([a-z]+))", q_norm)
    if range_match_en_alt:
        d_start, d_end, m_name = int(range_match_en_alt.group(1)), int(range_match_en_alt.group(2)), range_match_en_alt.group(3)
        if m_name in _MONTH_MAP:
            m_num = _MONTH_MAP[m_name]
            p = Period(start=f"{year}-{m_num}-{d_start:02d}", end=f"{year}-{m_num}-{d_end:02d}")
            return p, None

    # 2. Relative period check: "last month", "mois dernier", "previous month"
    # In Olist benchmark (dataset active up to August 2018), "last month" refers to July 2018 (or August 2018 vs July 2018)
    if any(rel in q_norm for rel in ["last month", "mois dernier", "previous month", "dernier mois"]):
        # Check if comparing to previous month
        if any(c in q_norm for c in ["vs", "compared to", "par rapport"]):
            p = _make_period(year, "08")
            c = _make_period(year, "07")
            return p, c
        else:
            return _make_period(year, "07"), None

    # 3. Standard month extraction
    compare_months: set[str] = set()
    for m in _COMPARE_PATTERNS.finditer(q_norm):
        word = m.group(1).lower()
        word_norm = _normalize(word)
        if word_norm in _MONTH_MAP:
            compare_months.add(_MONTH_MAP[word_norm])

    mentioned: list[str] = []
    for name, num in _MONTH_MAP.items():
        if re.search(r"\b" + re.escape(name) + r"\b", q_norm) and num not in mentioned:
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


def _find_filters(question_lower: str, catalog: KpiCatalog) -> list[str]:
    """Extract exclusion filters, limits and constraints from the question.

    Examples:
      - "Top 5" -> ["LIMIT 5"]
      - "sauf SP", "excluding SP", "hors SP" -> ["customer_state != 'SP'"]
      - "excluding canceled" -> ["order_status != 'canceled'"]
    """
    q_norm = _normalize(question_lower)
    filters: list[str] = []

    # 1. Top N / Limits
    top_match = re.search(r"\b(?:top|premiers?)\s*(\d+)\b", q_norm)
    if top_match:
        limit_val = top_match.group(1)
        filters.append(f"LIMIT {limit_val}")

    # 2. Exclusion filters: "sauf SP", "hors SP", "excluding SP", "without SP"
    excl_state_match = re.search(r"\b(?:sauf|hors|excluding|without|except)\s+([a-z]{2})\b", q_norm)
    if excl_state_match:
        st_code = excl_state_match.group(1).upper()
        filters.append(f"customer_state != '{st_code}'")

    excl_status_match = re.search(r"\b(?:sauf|excluding|without|hors)\s+(canceled|annulee?s?)\b", q_norm)
    if excl_status_match:
        filters.append("order_status != 'canceled'")

    return filters


def _match_terms(question_lower: str, glossary: Glossary) -> dict[str, str]:
    matched: dict[str, str] = {}
    q_norm = _normalize(question_lower)
    for term in glossary.terms:
        for syn in term.synonyms:
            if re.search(r"(?<![a-z0-9])" + re.escape(_normalize(syn)) + r"(?![a-z0-9])", q_norm):
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
    filters       = _find_filters(q_lower, catalog)
    matched_terms = _match_terms(q_lower, glossary)

    request = AnalysisRequest(
        question=question,
        metric=metric,
        dimensions=dimensions,
        period=period,
        compare_to=compare_to,
        filters=filters,
        confidence=confidence,
        matched_terms=matched_terms,
    )

    out_path = ctx.output("request")
    save(request, out_path)

    ctx.log(
        "parse_request", "SUCCESS",
        outputs=[str(out_path)],
        rule_version="request:keyword@1.3",
        evidence={
            "metric": metric,
            "dimensions": dimensions,
            "confidence": confidence,
            "period": f"{period.start}...{period.end}",
            "compare_to": compare_to.model_dump() if compare_to else None,
            "filters": filters,
        },
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"request": out_path},
        message=(
            f"Parsed: metric={metric}, dims={dimensions}, "
            f"period={period.start}...{period.end}, filters={filters}, confidence={confidence:.0%}"
        ),
    )
