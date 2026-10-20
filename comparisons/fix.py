"""Proposed adjustments. A fix only changes PERIODS or SCALE, never the metric or
the dimensions, and is never applied without the user's confirmation.
Every value is recomputed in SQL with the catalog definition.
"""
from datetime import date, timedelta

from comparisons.checks import EdgeCoverage
from comparisons.data import Inputs, days_of
from contracts.common import Period
from contracts.comparisons import CheckStatus, ComparisonCheck, FixMethod, ProposedFix


def _shift(p: Period, lo: int, hi: int) -> Period:
    s = date.fromisoformat(p.start)
    return Period(start=(s + timedelta(days=lo)).isoformat(), end=(s + timedelta(days=hi)).isoformat())


def _offsets(ec: EdgeCoverage) -> tuple[int, int]:
    s = date.fromisoformat(ec.period.start)
    return ((date.fromisoformat(ec.complete.start) - s).days,
            (date.fromisoformat(ec.complete.end) - s).days)


def _change(cur: float, prev: float) -> float | None:
    return round(cur / prev - 1, 4) if prev else None


def same_days(inp: Inputs, cur: Period, prev: Period, lo: int, hi: int, why: str) -> ProposedFix:
    a, b = _shift(cur, lo, hi), _shift(prev, lo, hi)
    va, vb = inp.kpi_value(a), inp.kpi_value(b)
    return ProposedFix(
        method=FixMethod.SAME_DAYS, unit=inp.kpi.unit,
        description=f"Compare days {lo + 1} to {hi + 1} of both periods: {a.start}..{a.end} "
                    f"with {b.start}..{b.end}.",
        justification=why, period=a, compare_to=b,
        value_current=va, value_previous=vb, change_pct=_change(va, vb))


def per_day(inp: Inputs, a: Period, b: Period, why: str) -> ProposedFix:
    na, nb = len(days_of(a)), len(days_of(b))
    va, vb = round(inp.kpi_value(a) / na, 2), round(inp.kpi_value(b) / nb, 2)
    return ProposedFix(
        method=FixMethod.PER_DAY_AVERAGE, unit=f"{inp.kpi.unit}/day",
        description=f"Compare {inp.kpi.name} per day: {a.start}..{a.end} ({na} days) "
                    f"with {b.start}..{b.end} ({nb} days).",
        justification=why, period=a, compare_to=b,
        value_current=va, value_previous=vb, change_pct=_change(va, vb))


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
                        f"Days {lo + 1} to {hi + 1} are complete in both periods ({n} days). "
                        f"Using the same days compares equal amounts of time.")
        alts = []
        if inp.additive:
            full_prev = inp.kpi_value(prev.complete)
            outside = 1 - (rec.value_previous / full_prev) if full_prev else 0.0
            alts.append(per_day(inp, cur.complete, prev.complete,
                                f"Uses every complete day of both periods "
                                f"({len(days_of(cur.complete))} and {len(days_of(prev.complete))} days). "
                                f"In the previous period, {outside:.1%} of the value falls on days "
                                f"the same-days comparison leaves out."))
        return rec, alts

    if scale.status in (CheckStatus.BLOCKING, CheckStatus.WARNING):
        n = min(len(days_of(req.period)), len(days_of(req.compare_to)))
        rec = per_day(inp, req.period, req.compare_to,
                      f"The periods have different lengths ({scale.evidence['days_current']} and "
                      f"{scale.evidence['days_previous']} days). A daily average removes the length effect.")
        alt = same_days(inp, req.period, req.compare_to, 0, n - 1,
                        f"Keeps totals but uses only the first {n} days of each period.")
        return rec, [alt]

    return None, []
