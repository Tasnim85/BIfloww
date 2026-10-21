"""Proposed adjustments. A fix only changes PERIODS or SCALE, never the metric or
the dimensions, and is never applied without the user's confirmation.
Every value is recomputed in SQL with the catalog definition.
"""
from datetime import date, timedelta

from comparisons.checks import EdgeCoverage
from comparisons.data import Inputs, days_of
from contracts.common import Period
from contracts.comparisons import CheckStatus, ComparisonCheck, FixMethod, ProposedFix
from contracts.i18n import Msg, render


def _shift(p: Period, lo: int, hi: int) -> Period:
    s = date.fromisoformat(p.start)
    return Period(start=(s + timedelta(days=lo)).isoformat(), end=(s + timedelta(days=hi)).isoformat())


def _offsets(ec: EdgeCoverage) -> tuple[int, int]:
    s = date.fromisoformat(ec.period.start)
    return ((date.fromisoformat(ec.complete.start) - s).days,
            (date.fromisoformat(ec.complete.end) - s).days)


def _change(cur: float, prev: float) -> float | None:
    return round(cur / prev - 1, 4) if prev else None


def _fix(method: FixMethod, unit: Msg, what: Msg, why: Msg, **values) -> ProposedFix:
    """Texts in English (journal) and as messages (any language)."""
    return ProposedFix(method=method, unit=render(unit), description=render(what), justification=render(why),
                       unit_parts=[unit], description_parts=[what], justification_parts=[why], **values)


def same_days(inp: Inputs, cur: Period, prev: Period, lo: int, hi: int, why: Msg) -> ProposedFix:
    a, b = _shift(cur, lo, hi), _shift(prev, lo, hi)
    va, vb = inp.kpi_value(a), inp.kpi_value(b)
    what = Msg(key="fix.same_days", params={"first": lo + 1, "last": hi + 1, "a_start": a.start,
                                            "a_end": a.end, "b_start": b.start, "b_end": b.end})
    return _fix(FixMethod.SAME_DAYS, Msg(key="fix.unit", params={"unit": inp.kpi.unit}), what, why,
                period=a, compare_to=b, value_current=va, value_previous=vb, change_pct=_change(va, vb))


def per_day(inp: Inputs, a: Period, b: Period, why: Msg) -> ProposedFix:
    na, nb = len(days_of(a)), len(days_of(b))
    va, vb = round(inp.kpi_value(a) / na, 2), round(inp.kpi_value(b) / nb, 2)
    what = Msg(key="fix.per_day", params={"kpi": inp.kpi.name, "a_start": a.start, "a_end": a.end, "na": na,
                                          "b_start": b.start, "b_end": b.end, "nb": nb})
    return _fix(FixMethod.PER_DAY_AVERAGE, Msg(key="fix.unit_per_day", params={"unit": inp.kpi.unit}), what, why,
                period=a, compare_to=b, value_current=va, value_previous=vb, change_pct=_change(va, vb))


def propose_fixes(inp: Inputs, coverage: ComparisonCheck, edges: tuple[EdgeCoverage, EdgeCoverage],
                  scale: ComparisonCheck) -> tuple[ProposedFix | None, list[ProposedFix]]:
    """Returns (recommended fix, alternatives). (None, []) when nothing valid can be proposed."""
    req = inp.request
    cur, prev = edges

    if coverage.status == CheckStatus.BLOCKING:
        if cur.complete is None or prev.complete is None:
            return None, []          # no complete day on one side: nothing honest to compare
        (a, b), (c, d) = _offsets(cur), _offsets(prev)
        lo, hi = max(a, c), min(b, d)
        if lo > hi:
            return None, []
        n = hi - lo + 1
        rec = same_days(inp, req.period, req.compare_to, lo, hi,
                        Msg(key="fix.why_same_days", params={"first": lo + 1, "last": hi + 1, "n": n}))
        alts = []
        if inp.additive:
            full_prev = inp.kpi_value(prev.complete)
            outside = 1 - (rec.value_previous / full_prev) if full_prev else 0.0
            alts.append(per_day(inp, cur.complete, prev.complete, Msg(key="fix.why_per_day", params={
                "na": len(days_of(cur.complete)), "nb": len(days_of(prev.complete)), "outside": outside})))
        return rec, alts

    if scale.status in (CheckStatus.BLOCKING, CheckStatus.WARNING):
        n = min(len(days_of(req.period)), len(days_of(req.compare_to)))
        rec = per_day(inp, req.period, req.compare_to, Msg(key="fix.why_lengths", params={
            "n_cur": scale.evidence["days_current"], "n_prev": scale.evidence["days_previous"]}))
        alt = same_days(inp, req.period, req.compare_to, 0, n - 1, Msg(key="fix.why_first_days", params={"n": n}))
        return rec, [alt]

    return None, []
