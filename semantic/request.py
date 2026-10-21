"""semantic/request.py -- Step 4: request understanding (Malek -- BO4-06).

Turns a user's natural-language question into a validated AnalysisRequest
by searching the business glossary with sentence embeddings (Sentence-Transformers),
keyword matching, typo tolerance, filter detection, and period extraction.

Alignment with the contracts and the Analyst (v1.4):
  - glossary phrases are matched as whole words and the longest phrase wins
    ("seller state" -> seller_state, "state" -> customer_state, "mois de mai" is a period)
  - a dimension the KPI does not allow (`allowed_dimensions`) gives NEEDS_REVIEW
  - `filters` only holds SQL WHERE parts the Analyst accepts (contract AnalysisRequest):
    "Top N" is not a WHERE part, it goes to the audit evidence only
  - months are read in question order; "compared with", "comparé à", "contre"… are connectors;
    a year written after a month belongs to that month; a year alone is the whole year
  - matched_terms keeps the words of the question, as in contracts/examples
"""
from __future__ import annotations

import calendar
import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import Period, load, save
from contracts.intake import Upload
from contracts.semantic import AnalysisRequest, Glossary, KpiCatalog, KpiDefinition, load_yaml

logger = logging.getLogger(__name__)

RULE_VERSION = "request:embeddings+keyword@1.4"
DEFAULT_YEAR = "2018"   # Olist dataset reference year, used only when the question has no year

# Cache for sentence-transformers model (BO4-06 embedding search)
_EMB_MODEL: Any = None
_EMB_MODEL_TRIED: bool = False


def _get_embedding_model() -> Any:
    """Lazy-load the SentenceTransformer model (offline/cached if available)."""
    global _EMB_MODEL, _EMB_MODEL_TRIED
    if _EMB_MODEL_TRIED:
        return _EMB_MODEL
    _EMB_MODEL_TRIED = True
    try:
        from sentence_transformers import SentenceTransformer
        _EMB_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as exc:
        logger.warning("SentenceTransformer not available in request parser: %s", exc)
        _EMB_MODEL = None
    return _EMB_MODEL


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
    # English abbreviations
    "jan": "01", "feb": "02", "apr": "04", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "sept": "09", "oct": "10", "nov": "11", "dec": "12",
}

# Comparison connectors -- a month written AFTER one of these words is compare_to
_COMPARE_PATTERNS = re.compile(
    r"\b(?:vs\.?|versus|compared\s+(?:to|with)|than|against|"
    r"par\s+rapport\s+(?:a|au|aux)|compare(?:e|s|es)?\s+(?:a|au|aux|avec)|contre|face\s+a)\b",
    re.IGNORECASE,
)

# "August", "August 2018", "mois de mai", "month of May" -- one span, so "month"/"mois"
# around a month name is part of the period, not the order_month dimension.
_MONTH_PATTERN = re.compile(
    r"\b(?:(?:the\s+)?month\s+of\s+|(?:le\s+|au\s+|du\s+)?mois\s+(?:de\s+|d')?)?"
    r"(" + "|".join(sorted(_MONTH_MAP, key=len, reverse=True)) + r")\b\.?"
    r"(?:\s+(?:of\s+)?((?:19|20)\d{2})\b)?",
    re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")


def _plain(text: str) -> str:
    """Like _normalize, but every character keeps its position ('Région' -> 'region'),
    so a phrase found in the plain text points at the same words in the question."""
    out = []
    for ch in text.replace("\u2019", "'").replace("\u2018", "'"):
        base = unicodedata.normalize("NFD", ch)[0]
        out.append(base.lower() if len(base.lower()) == 1 else base)
    return "".join(out)


def _words(name: str) -> str:
    """KPI or dimension name -> words: 'AverageBasket' -> 'average basket', 'customer_state' -> 'customer state'."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ")
    return " ".join(spaced.split()).lower()


def _is_acronym(phrase: str) -> bool:
    """CA, AOV: matched on the lower-case question WITH its accents, so 'ça' is not 'CA'."""
    return phrase.strip().isupper() and len(phrase.strip()) <= 4


def _phrase_regex(phrase: str) -> re.Pattern:
    """Whole words only; a plural 's' (or 'y' -> 'ies') is accepted; spaces are flexible."""
    if _is_acronym(phrase):
        return re.compile(r"(?<!\w)" + re.escape(phrase.strip().lower()) + r"(?!\w)")
    body = r"\s+".join(re.escape(w) for w in _plain(phrase.strip()).split())
    body = body[:-1] + r"(?:y|ies)" if body.endswith("y") else body + r"(?:s|es)?"
    return re.compile(r"(?<!\w)" + body + r"(?!\w)")


@dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    words: str      # as written in the question, e.g. "chiffre d'affaires"
    term: str       # catalog name, e.g. "Revenue"
    kind: str       # "metric" | "dimension" | "time" | "month"
    is_name: bool   # the KPI / dimension name itself, not a synonym


def _vocabulary(catalog: KpiCatalog | None, glossary: Glossary | None) -> list[tuple[str, str, str, bool]]:
    """(phrase, catalog name, kind, is_name) for every name and synonym the question may use.

    A glossary term that is not in the catalog is skipped: the request only names
    KPIs and dimensions the Analyst knows.
    """
    kpis = {k.name for k in catalog.kpis} if catalog else set()
    dims = {d.name for d in catalog.dimensions} if catalog else set()
    vocab: list[tuple[str, str, str, bool]] = []
    for names, kind in ((kpis, "metric"), (dims, "dimension")):
        for name in names:
            vocab += [(name, name, kind, True), (_words(name), name, kind, True)]
    for term in (glossary.terms if glossary else []):
        kind = term.kind.lower()
        if catalog and kind == "metric" and term.term not in kpis:
            continue
        if catalog and kind == "dimension" and term.term not in dims:
            continue
        vocab += [(phrase, term.term, kind, False) for phrase in [term.term, *term.synonyms]]
    return vocab


def _scan(question: str, catalog: KpiCatalog | None, glossary: Glossary | None) -> list[_Hit]:
    """Every glossary phrase and month found in the question, without overlaps, in question order.

    When two phrases overlap the longest wins: "number of orders" beats "orders",
    "seller state" beats "state", "last month" beats "month", "mois de mai" is a month.
    """
    plain, lower = _plain(question), question.lower()
    if len(lower) != len(question):          # rare characters that change length: no accents kept
        lower = plain
    found: list[_Hit] = []
    for phrase, term, kind, is_name in _vocabulary(catalog, glossary):
        text = lower if _is_acronym(phrase) else plain
        for m in _phrase_regex(phrase).finditer(text):
            found.append(_Hit(m.start(), m.end(), question[m.start():m.end()], term, kind, is_name))
    for m in _MONTH_PATTERN.finditer(plain):
        found.append(_Hit(m.start(), m.end(), question[m.start():m.end()], "month", "month", False))

    chosen: list[_Hit] = []
    for hit in sorted(found, key=lambda h: (-(h.end - h.start), h.start)):
        if all(hit.end <= c.start or hit.start >= c.end for c in chosen):
            chosen.append(hit)
    return sorted(chosen, key=lambda h: h.start)


def _find_metric(
    question_lower: str,
    catalog: KpiCatalog,
    glossary: Glossary | None = None,
) -> tuple[str | None, float]:
    """Return (metric_name, confidence) or (None, 0.0) if no match.

    Resolution order:
      1. Direct KPI name match           (conf 0.90)
      3. Glossary synonym match          (conf 0.75)
      2. KPI name word-split token       (conf 0.60)
      4. Embedding cosine similarity     (conf 0.80)  -- NEW: sentence-transformers vector search
      5. Typo-tolerant fuzzy match       (conf 0.65)
      6. Return (None, 0.0)
    """
    q = question_lower
    q_norm = _normalize(q)
    metric_hits = [h for h in _scan(q, catalog, glossary) if h.kind == "metric"]

    # Tier 1: exact KPI name in question (whole words, first one in the question)
    names = [h for h in metric_hits if h.is_name]
    if names:
        return names[0].term, 0.90

    # Tier 3 (before tier 2, so "number of orders" is a synonym, not a piece of a name):
    # glossary synonyms for metric terms, whole words, longest phrase wins
    if metric_hits:
        return metric_hits[0].term, 0.75

    # Tier 2: one word of a KPI name ("basket" -> AverageBasket), whole words only
    plain = _plain(q)
    for kpi in catalog.kpis:
        for kw in _words(kpi.name).split():
            if len(kw) > 3 and _phrase_regex(kw).search(plain):
                return kpi.name, 0.60

    # Tier 4: Embedding cosine similarity search against Glossary & Catalog descriptions
    emb_model = _get_embedding_model()
    if emb_model is not None and glossary is not None:
        try:
            import numpy as np
            metric_candidates: list[tuple[str, str]] = [] # (kpi_name, text_description)
            for kpi in catalog.kpis:
                metric_candidates.append((kpi.name, f"{kpi.name}: {kpi.description}"))
            for term in glossary.terms:
                if term.kind == "metric":
                    matched_kpi = next((k.name for k in catalog.kpis if k.name.lower() == term.term.lower()), None)
                    if matched_kpi:
                        metric_candidates.append((matched_kpi, f"{term.term} - {term.definition} {' '.join(term.synonyms)}"))

            cand_texts = [c[1] for c in metric_candidates]
            cand_embs = emb_model.encode(cand_texts, convert_to_numpy=True, normalize_embeddings=True)
            q_emb = emb_model.encode([q_norm], convert_to_numpy=True, normalize_embeddings=True)
            sims = np.dot(q_emb, cand_embs.T)[0]
            best_idx = int(np.argmax(sims))
            best_score = float(sims[best_idx])
            if best_score >= 0.58:
                return metric_candidates[best_idx][0], round(min(0.85, best_score), 2)
        except Exception as exc:
            logger.warning("Embedding search failed in _find_metric: %s", exc)

    # Tier 5: Typo tolerance via difflib on tokens
    words = re.findall(r"[a-z0-9']+", q_norm)
    all_metric_targets: dict[str, str] = {}
    for kpi in catalog.kpis:
        all_metric_targets[_normalize(kpi.name)] = kpi.name
    if glossary is not None:
        for term in glossary.terms:
            if term.kind == "metric":
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
    """Return catalog dimension names mentioned in the question, in question order.

    Dimension names and glossary synonyms, whole words, the longest phrase wins:
    "seller state" -> seller_state, "state" alone -> customer_state, the word "order"
    never adds order_month. Fuzzy matching only when nothing was found.
    """
    q_norm = _normalize(question_lower)
    found: list[str] = []
    dim_names = {dim.name for dim in catalog.dimensions}

    # 1. Glossary phrases (catalog dimensions only)
    for hit in _scan(question_lower, catalog, glossary):
        if hit.kind == "dimension" and hit.term not in found:
            found.append(hit.term)

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


def _day_range(year: str, month: str, d_start: int, d_end: int) -> Period | None:
    """'du 5 au 20 juin' -> 2018-06-05..2018-06-20; None if a day does not exist (31 juin)."""
    try:
        start = date(int(year), int(month), d_start)
        end = date(int(year), int(month), d_end)
    except ValueError:
        return None
    return Period(start=start.isoformat(), end=end.isoformat()) if start <= end else None


def _find_period(question_lower: str) -> tuple[Period | None, Period | None]:
    """Extract main period and optional comparison period from the question.

    Supports:
      - Explicit date range: "du 5 au 20 juin", "from June 5 to June 20"
      - Relative periods: "last month", "mois dernier", "previous month"
      - Month names (EN/FR) with optional comparison connectors: "August vs July"
    """
    q_norm = _normalize(question_lower)

    year_match = _YEAR_PATTERN.search(q_norm)
    year = year_match.group(1) if year_match else DEFAULT_YEAR  # Olist dataset reference year

    # 1. Explicit day-range check: "du 5 au 20 juin", "from 5 to 20 june", "from june 5 to june 20"
    range_match_fr = re.search(r"\b(?:du\s+(\d{1,2})\s+au\s+(\d{1,2})\s+([a-z]+))", q_norm)
    if range_match_fr:
        d_start, d_end, m_name = int(range_match_fr.group(1)), int(range_match_fr.group(2)), range_match_fr.group(3)
        if m_name in _MONTH_MAP:
            m_num = _MONTH_MAP[m_name]
            return _day_range(year, m_num, d_start, d_end), None

    range_match_en = re.search(r"\b(?:from\s+([a-z]+)\s+(\d{1,2})\s+to\s+(?:[a-z]+\s+)?(\d{1,2}))", q_norm)
    if range_match_en:
        m_name, d_start, d_end = range_match_en.group(1), int(range_match_en.group(2)), int(range_match_en.group(3))
        if m_name in _MONTH_MAP:
            m_num = _MONTH_MAP[m_name]
            return _day_range(year, m_num, d_start, d_end), None

    range_match_en_alt = re.search(r"\b(?:from\s+(\d{1,2})\s+to\s+(\d{1,2})\s+([a-z]+))", q_norm)
    if range_match_en_alt:
        d_start, d_end, m_name = int(range_match_en_alt.group(1)), int(range_match_en_alt.group(2)), range_match_en_alt.group(3)
        if m_name in _MONTH_MAP:
            m_num = _MONTH_MAP[m_name]
            return _day_range(year, m_num, d_start, d_end), None

    # 2. Relative period check: "last month", "mois dernier", "previous month"
    if any(rel in q_norm for rel in ["last month", "mois dernier", "previous month", "dernier mois"]):
        if any(c in q_norm for c in ["vs", "compared to", "par rapport"]):
            p = _make_period(year, "08")
            c = _make_period(year, "07")
            return p, c
        else:
            return _make_period(year, "07"), None

    # 3. Months in question order. A month written after a connector ("vs", "compared with",
    #    "par rapport a"...) is compare_to; the first other month is the main period.
    #    A year written right after a month belongs to that month.
    months: list[tuple[str, str, bool]] = []      # (month, year, after a connector)
    previous_end = 0
    for m in _MONTH_PATTERN.finditer(q_norm):
        is_compare = bool(_COMPARE_PATTERNS.search(q_norm, previous_end, m.start()))
        months.append((_MONTH_MAP[m.group(1).lower()], m.group(2) or year, is_compare))
        previous_end = m.end()

    if not months:
        if year_match:   # "Revenue by month in 2017" -> the whole year
            return Period(start=f"{year}-01-01", end=f"{year}-12-31"), None
        return None, None

    main = next((mo for mo in months if not mo[2]), months[0])
    others = [mo for mo in months if mo is not main and mo[:2] != main[:2]]
    compare = next((mo for mo in others if mo[2]), others[0] if others else None)

    period  = _make_period(main[1], main[0])
    compare_to = _make_period(compare[1], compare[0]) if compare else None
    return period, compare_to


_NOT_A_CODE = {"de", "du", "la", "le", "un", "en", "au", "si", "on", "of", "in", "to", "me", "us",
               "it", "an", "at", "by", "my", "ca"}


def _find_top_n(question_lower: str) -> int | None:
    """'Top 5 categories' -> 5. Not a WHERE part, so it never goes into `filters`."""
    top_match = re.search(r"\b(?:top|premiers?)\s*(\d+)\b", _normalize(question_lower))
    return int(top_match.group(1)) if top_match else None


def _find_filters(question_lower: str, catalog: KpiCatalog) -> list[str]:
    """Extract exclusion filters from the question, as SQL WHERE parts (contract AnalysisRequest).

    Examples:
      - "sauf SP", "excluding SP", "hors SP" -> ["customer_state != 'SP'"]
      - "excluding canceled" -> ["order_status != 'canceled'"]
    "Top 5" is a limit, not a WHERE part: see _find_top_n.
    """
    q_norm = _normalize(question_lower)
    filters: list[str] = []

    # Exclusion filters: "sauf SP", "hors SP", "excluding SP", "without SP"
    excl_state_match = re.search(r"\b(?:sauf|hors|excluding|without|except)\s+([a-z]{2})\b", q_norm)
    if excl_state_match and excl_state_match.group(1) not in _NOT_A_CODE:
        st_code = excl_state_match.group(1).upper()
        filters.append(f"customer_state != '{st_code}'")

    excl_status_match = re.search(r"\b(?:sauf|excluding|without|hors)\s+(canceled|annulee?s?)\b", q_norm)
    if excl_status_match:
        filters.append("order_status != 'canceled'")

    return filters


def _match_terms(question: str, glossary: Glossary,
                 catalog: KpiCatalog | None = None) -> dict[str, str]:
    """Words of the question -> glossary term, e.g. {"sales": "Revenue", "region": "customer_state"}."""
    return {h.words: h.term for h in _scan(question, catalog, glossary)
            if h.kind in ("metric", "dimension", "time")}


def _check_filters(filters: list[str], dimensions: list[str],
                   kpi: KpiDefinition) -> tuple[list[str], list[str], list[str], list[str]]:
    """Keep only filters the Analyst accepts: a simple condition on a dimension the KPI allows,
    present in the breakdown. Returns (filters, dimensions, redundant, refused)."""
    kept, dims, redundant, refused = [], list(dimensions), [], []
    for flt in filters:
        column = re.match(r"\s*(\w+)", flt).group(1)
        if column in kpi.allowed_dimensions:
            if column not in dims:
                dims.append(column)     # the Analyst filters only on a dimension of the breakdown
            kept.append(flt)
        elif any(re.match(rf"\s*{column}\s*=", f) for f in kpi.filters):
            redundant.append(flt)       # e.g. "order_status != 'canceled'" when the KPI keeps 'delivered'
        else:
            refused.append(flt)
    return kept, dims, redundant, refused


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

    # Pass glossary into _find_metric so synonyms & embeddings are resolved
    metric, confidence = _find_metric(q_lower, catalog, glossary)
    if metric is None:
        ctx.log(
            "parse_request", "NEEDS_REVIEW", rule_version=RULE_VERSION,
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
            "parse_request", "NEEDS_REVIEW", rule_version=RULE_VERSION,
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
    top_n         = _find_top_n(q_lower)
    kpi = next(k for k in catalog.kpis if k.name == metric)
    filters, dimensions, redundant, refused_filters = _check_filters(
        _find_filters(q_lower, catalog), dimensions, kpi)
    refused_dims = [d for d in dimensions if d not in kpi.allowed_dimensions]
    if refused_dims or refused_filters:
        ctx.log(
            "parse_request", "NEEDS_REVIEW", rule_version=RULE_VERSION,
            evidence={"question": question, "metric": metric,
                      "reason": "dimension or filter not allowed for this KPI",
                      "dimensions": refused_dims, "filters": refused_filters,
                      "allowed_dimensions": kpi.allowed_dimensions},
        )
        refused = ", ".join(refused_dims + refused_filters)
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.NEEDS_REVIEW,
            message=(
                f"{metric} cannot be split or filtered by {refused}. "
                f"Allowed: {', '.join(kpi.allowed_dimensions)}."
            ),
        )
    matched_terms = _match_terms(question, glossary, catalog)

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
        rule_version=RULE_VERSION,
        evidence={
            "metric": metric,
            "dimensions": dimensions,
            "confidence": confidence,
            "period": f"{period.start}...{period.end}",
            "compare_to": compare_to.model_dump() if compare_to else None,
            "filters": filters,
            "redundant_filters": redundant,
            "top_n": top_n,              # no field for it in AnalysisRequest v1.1
            "matched_terms": matched_terms,
            "embedding_used": _get_embedding_model() is not None,
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
