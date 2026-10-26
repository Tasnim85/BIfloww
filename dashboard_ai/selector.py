"""Optimal chart choice: every ChartType gets a score and a list of reasons.

Hard rules first (can this chart tell the truth with THIS data?), then preferences
(what does the question want to see?). The best eligible type wins. A chart the user asked
for explicitly wins only if it is eligible; otherwise the refusal is explained.
"""
from contracts.dashboard import ChartType
from dashboard_ai.intent import Intent
from dashboard_ai.messages import t
from dashboard_ai.models import ChartCandidate
from dashboard_ai.profile import DataProfile
from dashboard_ai.rules import Rules


def score_candidates(p: DataProfile, intent: Intent, requested: ChartType | None, rules: Rules,
                     lang: str, comparison_shown: bool) -> list[ChartCandidate]:
    nd = len(p.dims)
    prim = p.primary
    n = prim.cardinality if prim else 0
    out: list[ChartCandidate] = []

    # ---- kpi_card
    if nd == 0:
        out.append(ChartCandidate(chart_type=ChartType.KPI_CARD, score=100, eligible=True, reasons=[t("why.kpi", lang)]))
    else:
        out.append(ChartCandidate(chart_type=ChartType.KPI_CARD, score=0, eligible=False, reasons=[t("kpi.has_dims", lang)]))

    # ---- line
    blockers = []
    if nd == 0 or nd > 2:
        blockers.append(t("line.not_temporal", lang, dim=prim.name if prim else "-"))
    elif not p.temporal:
        blockers.append(t("line.not_temporal", lang, dim=prim.name))
    elif n < rules.line_min_points:
        blockers.append(t("line.few_points", lang, n=n, min=rules.line_min_points))
    if blockers:
        out.append(ChartCandidate(chart_type=ChartType.LINE, score=0, eligible=False, reasons=blockers))
    else:
        why = t("why.line_cmp", lang) if comparison_shown else t("why.line", lang, n=n)
        out.append(ChartCandidate(chart_type=ChartType.LINE, score=90 + (5 if intent == Intent.TREND else 0),
                                  eligible=True, reasons=[why]))

    # ---- bar
    if nd == 0 or nd > 2:
        out.append(ChartCandidate(chart_type=ChartType.BAR, score=0, eligible=False, reasons=[t("bar.shape", lang)]))
    else:
        score = 75 + (10 if intent == Intent.RANKING else 0) + (10 if comparison_shown else 0)
        if p.temporal and n >= rules.line_min_points:
            score -= 25                      # a time axis is better served by a line
        if n > rules.bar_max_categories:
            score -= 5
        why = (t("why.bar_cmp", lang) if comparison_shown else
               t("why.bar_rank", lang, n=n) if intent == Intent.RANKING else t("why.bar", lang, n=n))
        out.append(ChartCandidate(chart_type=ChartType.BAR, score=score, eligible=True, reasons=[why]))

    # ---- pie
    blockers = []
    if nd != 1 or p.temporal:
        blockers.append(t("pie.shape", lang))
    else:
        if n > rules.pie_max_slices:
            blockers.append(t("pie.too_many", lang, n=n, max=rules.pie_max_slices))
        if n < rules.pie_min_slices:
            blockers.append(t("pie.too_few", lang, min=rules.pie_min_slices))
        if not p.additive:
            blockers.append(t("pie.not_additive", lang, metric=p.metric))
        if p.has_negative:
            blockers.append(t("pie.negative", lang))
        if comparison_shown:
            blockers.append(t("pie.multi_period", lang))
    if blockers:
        out.append(ChartCandidate(chart_type=ChartType.PIE, score=0, eligible=False, reasons=blockers))
    else:
        out.append(ChartCandidate(chart_type=ChartType.PIE, score=55 + (30 if intent == Intent.COMPOSITION else 0),
                                  eligible=True, reasons=[t("why.pie", lang, n=n)]))

    # ---- table (always possible: the honest fallback)
    many = nd >= 3 or intent == Intent.DETAIL
    out.append(ChartCandidate(chart_type=ChartType.TABLE, score=85 if many else 30, eligible=True,
                              reasons=[t("why.table", lang) if many else t("why.table_fallback", lang)]))

    # ---- map
    if not rules.map_enabled:
        out.append(ChartCandidate(chart_type=ChartType.MAP, score=0, eligible=False, reasons=[t("map.disabled", lang)]))
    elif nd == 1 and prim.kind == "geographic":
        out.append(ChartCandidate(chart_type=ChartType.MAP, score=70, eligible=True, reasons=[t("why.bar", lang, n=n)]))
    else:
        out.append(ChartCandidate(chart_type=ChartType.MAP, score=0, eligible=False, reasons=[t("map.not_geo", lang)]))

    # ---- explicit request wins when it is eligible
    if requested is not None:
        for c in out:
            if c.chart_type == requested and c.eligible:
                c.score += 40
                c.reasons.insert(0, t("why.requested", lang))
    return sorted(out, key=lambda c: (c.eligible, c.score), reverse=True)
