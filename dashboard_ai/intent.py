"""What does the question want to SEE? Keyword intent (FR/EN) + an explicit chart request.

BO4-06 already extracted metric, dimensions and periods. This only reads the *shape* of
the wish: trend, share, ranking, comparison, detail -- and "give me a pie chart".
"""
import re
import unicodedata
from enum import Enum

from contracts.dashboard import ChartType


class Intent(str, Enum):
    TOTAL = "total"
    TREND = "trend"
    COMPOSITION = "composition"
    RANKING = "ranking"
    COMPARISON = "comparison"
    DETAIL = "detail"
    NONE = "none"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


_INTENT_WORDS = {
    Intent.TREND: r"evolution|trend|tendance|over time|au fil|par mois|par jour|par semaine|monthly|mensuel|daily|"
                  r"quotidien|per month|by month|per day|by day|progression|croissance|growth",
    Intent.COMPOSITION: r"share|part de|parts de|repartition|proportion|composition|pourcentage|% of|split|"
                        r"breakdown|poids|contribution|combien represente",
    Intent.RANKING: r"\btop\b|best|worst|ranking|rank|classement|meilleur|pire|plus grand|plus gros|highest|lowest|"
                    r"leader|premier",
    Intent.COMPARISON: r"compar|versus|\bvs\b|\bcontre\b|par rapport|than|difference|ecart",
    Intent.DETAIL: r"detail|liste|list|toutes les lignes|tableau|table\b|show all|afficher tout",
}

_CHART_WORDS = {
    ChartType.PIE: r"pie|camembert|donut|secteur|fromage",
    ChartType.LINE: r"\bline\b|line chart|courbe|ligne",
    ChartType.BAR: r"\bbar\b|bars|barres|histogramme|baton|column chart",
    ChartType.TABLE: r"\btable\b|tableau",
    ChartType.MAP: r"\bmap\b|\bcarte\b|cartographie",
    ChartType.KPI_CARD: r"kpi card|carte kpi|indicateur",
}


def detect_requested_chart(question: str) -> ChartType | None:
    q = _norm(question)
    for chart, pattern in _CHART_WORDS.items():
        if re.search(pattern, q):
            return chart
    return None


def detect_intent(question: str, *, n_dims: int, temporal: bool, has_comparison: bool) -> Intent:
    q = _norm(question)
    if n_dims == 0:
        return Intent.TOTAL
    if n_dims >= 3:
        return Intent.DETAIL
    hits = {i for i, p in _INTENT_WORDS.items() if re.search(p, q)}
    if Intent.COMPOSITION in hits and not has_comparison:
        return Intent.COMPOSITION
    if has_comparison:
        return Intent.COMPARISON
    for intent in (Intent.TREND, Intent.RANKING, Intent.DETAIL, Intent.COMPARISON):
        if intent in hits:
            return intent
    return Intent.TREND if temporal else Intent.NONE
