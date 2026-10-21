"""The 5 comparability checks of BO4-12. Each one returns a ComparisonCheck:
ok / warning / blocking, a plain sentence, and the numbers behind it (evidence).

  coverage    PERIODS            are both periods complete at their edges?   (DQ profile)
  population  POPULATIONS        same scope on both sides?                   (SEM + SQL)
  unit        SCALES             same unit?                                  (SEM)
  scale       SCALES             same length, for totals?                    (SEM)
  grain       AGGREGATION LEVEL  same row meaning, no duplicated rows?       (ETL receipts + SQL)

The checks judge comparability only. They never change the metric or the dimensions.
"""
from dataclasses import dataclass, field
from statistics import median

from comparisons.data import Inputs, days_of
from comparisons.rules import Rules
from contracts.common import Period
from contracts.comparisons import CheckKind, CheckStatus, ComparisonCheck
from contracts.i18n import Msg, render

OK, WARNING, BLOCKING = CheckStatus.OK, CheckStatus.WARNING, CheckStatus.BLOCKING


def check(kind: CheckKind, status: CheckStatus, parts: list[Msg], evidence: dict) -> ComparisonCheck:
    """A check with its sentence in English (journal) and as messages (any language)."""
    return ComparisonCheck(kind=kind, status=status, message=render(parts), message_parts=parts,
                           evidence=evidence)


# ---- 1. Coverage ------------------------------------------------------------------
@dataclass
class EdgeCoverage:
    """Which part of a period has complete data."""
    period: Period
    complete: Period | None                 # None = not a single complete day
    threshold_rows: float
    baseline_median: float
    incomplete_days: dict = field(default_factory=dict)   # edge day -> rows

    @property
    def is_complete(self) -> bool:
        return self.complete == self.period


def edge_coverage(inp: Inputs, p: Period, other: Period, rules: Rules) -> EdgeCoverage:
    """Which days of `p` lie in an incomplete EDGE OF THE DATASET.

    Missing data shows up at the edges of the extraction, not at the edges of a month.
    So a low day counts as incomplete only if it belongs to the run of low days that
    reaches the very end (tail) or the very start (head) of the data. A quiet day
    followed by normal days (1 May, 1 January, a Sunday) is ordinary business.
    """
    baseline = float(median(d.rows for d in inp.coverage_days(other)))
    threshold = rules.min_volume_share * baseline
    status = inp.status_filter()

    def low(d) -> bool:
        if d.rows == 0 or d.rows < threshold:
            return True
        if status and d.by_status:      # rows exist but have not reached the KPI status yet
            return d.by_status.get(status[1], 0) / d.rows < rules.min_status_share
        return False

    data = inp.coverage_table().days                   # every day of the dataset, in order
    tail_start = None                                  # first day of the final run of low days
    for d in reversed(data):
        if not low(d):
            break
        tail_start = d.date
    head_end = None                                    # last day of the opening run of low days
    for d in data:
        if not low(d):
            break
        head_end = d.date
    first, last = data[0].date, data[-1].date

    def incomplete(day: str) -> bool:
        return (day > last or day < first
                or (tail_start is not None and day >= tail_start)
                or (head_end is not None and day <= head_end))

    days = inp.coverage_days(p)
    good = [i for i, d in enumerate(days) if not incomplete(d.date)]
    if not good:
        return EdgeCoverage(p, None, threshold, baseline, {d.date: d.rows for d in days})
    i, j = good[0], good[-1]
    edges = {d.date: d.rows for d in days[:i] + days[j + 1:]}
    return EdgeCoverage(p, Period(start=days[i].date, end=days[j].date), threshold, baseline, edges)


def _describe(which: str, ec: EdgeCoverage, what: str) -> Msg:
    p = ec.period
    base = {"which": f"word.{which}", "start": p.start, "end": p.end, "what": what,
            "median": ec.baseline_median}
    if ec.complete is None:
        return Msg(key="cmp.coverage.none", params=base | {"max_rows": max(ec.incomplete_days.values(), default=0)})
    low = list(ec.incomplete_days.values())
    before, after = ec.complete.start != p.start, ec.complete.end != p.end
    key = "cmp.coverage." + ("both" if before and after else "before" if before else "after")
    return Msg(key=key, params=base | {"cstart": ec.complete.start, "cend": ec.complete.end,
                                       "lo": min(low), "hi": max(low)})


def check_coverage(inp: Inputs, rules: Rules, as_asked: tuple[float, float]):
    req = inp.request
    cur = edge_coverage(inp, req.period, req.compare_to, rules)
    prev = edge_coverage(inp, req.compare_to, req.period, rules)
    evidence = {
        "rule": (f"days in the run of low days that reaches the start or end of the data; low = "
                 f"volume < {rules.min_volume_share:.0%} of the other period's median, or "
                 f"< {rules.min_status_share:.0%} of rows with the KPI status"),
        "source": "profiling/coverage_profile.json",
        "table": inp.coverage_table().table,
        "current": {"period": req.period.model_dump(),
                    "complete": cur.complete.model_dump() if cur.complete else None,
                    "reference_median_rows": cur.baseline_median,
                    "threshold_rows": round(cur.threshold_rows, 1),
                    "incomplete_days": cur.incomplete_days},
        "previous": {"period": req.compare_to.model_dump(),
                     "complete": prev.complete.model_dump() if prev.complete else None,
                     "reference_median_rows": prev.baseline_median,
                     "threshold_rows": round(prev.threshold_rows, 1),
                     "incomplete_days": prev.incomplete_days},
    }
    if cur.complete:          # kept for the example and the dashboard
        evidence["last_complete_day"] = cur.complete.end
    if cur.is_complete and prev.is_complete:
        return check(CheckKind.COVERAGE, OK, [Msg(key="cmp.coverage.ok")], evidence), (cur, prev)

    what = inp.coverage_table().table
    parts = [_describe(n, ec, what) for n, ec in (("current", cur), ("previous", prev)) if not ec.is_complete]
    v_cur, v_prev = as_asked
    if v_prev:
        n_cur = len(days_of(cur.complete)) if cur.complete else 0
        n_prev = len(days_of(prev.complete)) if prev.complete else 0
        parts.append(Msg(key="cmp.coverage.as_asked",
                         params={"chg": v_cur / v_prev - 1, "n_cur": n_cur, "n_prev": n_prev}))
    return check(CheckKind.COVERAGE, BLOCKING, parts, evidence), (cur, prev)


# ---- 2. Population ---------------------------------------------------------------
def check_population(inp: Inputs, rules: Rules) -> ComparisonCheck:
    req = inp.request
    evidence: dict = {"kpi_filters": inp.kpi.filters, "request_filters": req.filters,
                      "population": inp.kpi.population}
    issues = []

    status = inp.status_filter()
    if status:
        shares = {}
        for name, p in (("current", req.period), ("previous", req.compare_to)):
            days = inp.coverage_days(p)
            total = sum(d.rows for d in days)
            shares[name] = sum(d.by_status.get(status[1], 0) for d in days) / total if total else 0.0
        evidence["status_share"] = {k: round(v, 4) for k, v in shares.items()}
        gap = abs(shares["current"] - shares["previous"])
        if gap > rules.status_share_gap:
            issues.append(Msg(key="cmp.population.status_share",
                              params={"cur": shares["current"], "prev": shares["previous"], "status": status[1]}))

    for dim in req.dimensions:
        a = inp.dimension_values(dim, req.period)
        b = inp.dimension_values(dim, req.compare_to)
        only_cur, only_prev = sorted(a - b), sorted(b - a)
        evidence[f"{dim}_only_current"] = only_cur
        evidence[f"{dim}_only_previous"] = only_prev
        if only_cur or only_prev:
            key = "only_both" if only_cur and only_prev else "only_current" if only_cur else "only_previous"
            issues.append(Msg(key=f"cmp.population.{key}", params={
                "label": dim.replace("_", " "), "only_cur": only_cur, "only_prev": only_prev}))

    if issues:
        return check(CheckKind.POPULATION, WARNING, issues, evidence)
    scope = inp.kpi.population or "the same filters"
    return check(CheckKind.POPULATION, OK, [Msg(key="cmp.population.ok", params={"scope": scope.rstrip(".")})],
                 evidence)


# ---- 3. Unit ------------------------------------------------------------------------
def check_unit(inp: Inputs) -> ComparisonCheck:
    evidence = {"catalog_unit": inp.kpi.unit, "catalog_kpi": inp.kpi.ref}
    if inp.result is not None:
        evidence.update(result_unit=inp.result.unit, result_kpi=inp.result.kpi)
        if inp.result.unit != inp.kpi.unit:
            return check(CheckKind.UNIT, BLOCKING, [Msg(key="cmp.unit.blocking", params={
                "result_unit": inp.result.unit, "kpi_ref": inp.kpi.ref, "kpi_unit": inp.kpi.unit})], evidence)
        if inp.result.kpi != inp.kpi.ref:
            return check(CheckKind.UNIT, WARNING, [Msg(key="cmp.unit.warning", params={
                "result_kpi": inp.result.kpi, "kpi_ref": inp.kpi.ref})], evidence)
    return check(CheckKind.UNIT, OK, [Msg(key="cmp.unit.ok", params={"unit": inp.kpi.unit, "kpi_ref": inp.kpi.ref})],
                 evidence)


# ---- 4. Scale -----------------------------------------------------------------------
def check_scale(inp: Inputs, rules: Rules) -> ComparisonCheck:
    n_cur, n_prev = len(days_of(inp.request.period)), len(days_of(inp.request.compare_to))
    gap = abs(n_cur - n_prev) / max(n_cur, n_prev)
    evidence = {"days_current": n_cur, "days_previous": n_prev, "length_gap": round(gap, 4),
                "additive_kpi": inp.additive, "expression": inp.kpi.expression}
    days = {"n_cur": n_cur, "n_prev": n_prev}
    if not inp.additive:
        return check(CheckKind.SCALE, OK, [Msg(key="cmp.scale.not_total", params={"kpi": inp.kpi.name})], evidence)
    if gap > rules.length_blocking:
        status = BLOCKING
    elif gap > rules.length_warning:
        status = WARNING
    else:
        return check(CheckKind.SCALE, OK, [Msg(key="cmp.scale.ok", params=days)], evidence)
    return check(CheckKind.SCALE, status, [Msg(key="cmp.scale.different",
                                               params=days | {"kpi": inp.kpi.name, "gap": gap})], evidence)


# ---- 5. Grain ------------------------------------------------------------------------
def check_grain(inp: Inputs) -> ComparisonCheck:
    fact = inp.fact
    evidence: dict = {"kpi_grain": inp.kpi.grain, "table": fact.name, "table_grain": fact.grain}
    problems = []
    if inp.kpi.grain != fact.grain:
        problems.append(Msg(key="cmp.grain.mismatch", params={
            "kpi_ref": inp.kpi.ref, "kpi_grain": inp.kpi.grain, "table": fact.name, "table_grain": fact.grain}))
    receipt = next((r for r in inp.receipts.receipts if r.output_table == fact.name), None)
    if receipt:
        evidence.update(rows_before=receipt.rows_before, rows_after=receipt.rows_after,
                        join_keys=receipt.join_keys)
        if receipt.rows_after > receipt.rows_before:
            problems.append(Msg(key="cmp.grain.join_duplicates", params={
                "table": fact.name, "before": receipt.rows_before, "after": receipt.rows_after,
                "keys": receipt.join_keys}))
    dups = inp.duplicate_keys()
    evidence["duplicate_primary_keys"] = dups
    if dups:
        problems.append(Msg(key="cmp.grain.duplicate_keys",
                            params={"dups": dups, "table": fact.name, "pk": fact.primary_key}))
    if problems:
        return check(CheckKind.GRAIN, BLOCKING, problems, evidence)
    return check(CheckKind.GRAIN, OK, [Msg(key="cmp.grain.ok", params={"table": fact.name, "grain": fact.grain})],
                 evidence)
