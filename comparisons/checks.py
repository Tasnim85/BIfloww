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

OK, WARNING, BLOCKING = CheckStatus.OK, CheckStatus.WARNING, CheckStatus.BLOCKING


def pct(x: float) -> str:
    return f"{x:+.1%}"


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


def _describe(name: str, ec: EdgeCoverage, what: str) -> str:
    p = ec.period
    if ec.complete is None:
        return (f"The {name} period ({p.start} to {p.end}) has no complete day: at most "
                f"{max(ec.incomplete_days.values(), default=0)} {what} per day, against a usual "
                f"{ec.baseline_median:.0f}.")
    low = [v for v in ec.incomplete_days.values()]
    where = []
    if ec.complete.start != p.start:
        where.append(f"before {ec.complete.start}")
    if ec.complete.end != p.end:
        where.append(f"after {ec.complete.end}")
    return (f"The {name} period ({p.start} to {p.end}) is complete only from {ec.complete.start} "
            f"to {ec.complete.end}: {' and '.join(where)} the volume falls to between "
            f"{min(low)} and {max(low)} {what} per day, against a usual {ec.baseline_median:.0f}.")


def check_coverage(inp: Inputs, rules: Rules, as_asked: tuple[float, float]):
    req = inp.request
    cur = edge_coverage(inp, req.period, req.compare_to, rules)
    prev = edge_coverage(inp, req.compare_to, req.period, rules)
    evidence = {
        "rule": (f"days in the run of low days that reaches the start or end of the data; low = "
                 f"volume < {rules.min_volume_share:.0%} of the other period's median, or "
                 f"< {rules.min_status_share:.0%} of rows with the KPI status"),
        "source": "profiling/coverage_profile.json",
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
        return ComparisonCheck(kind=CheckKind.COVERAGE, status=OK, evidence=evidence,
                               message="Both periods have complete data on every day."), (cur, prev)

    what = inp.coverage_table().table
    parts = [_describe(n, ec, what) for n, ec in (("current", cur), ("previous", prev)) if not ec.is_complete]
    v_cur, v_prev = as_asked
    if v_prev:
        n_cur = len(days_of(cur.complete)) if cur.complete else 0
        n_prev = len(days_of(prev.complete)) if prev.complete else 0
        parts.append(f"The comparison as asked ({pct(v_cur / v_prev - 1)}) compares {n_cur} "
                     f"complete days with {n_prev}.")
    return ComparisonCheck(kind=CheckKind.COVERAGE, status=BLOCKING, message=" ".join(parts),
                           evidence=evidence), (cur, prev)


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
            issues.append(f"{shares['current']:.1%} of the current period's orders are "
                          f"'{status[1]}', against {shares['previous']:.1%} in the previous one: "
                          f"the KPI keeps a different share of each period.")

    for dim in req.dimensions:
        a = inp.dimension_values(dim, req.period)
        b = inp.dimension_values(dim, req.compare_to)
        only_cur, only_prev = sorted(a - b), sorted(b - a)
        evidence[f"{dim}_only_current"] = only_cur
        evidence[f"{dim}_only_previous"] = only_prev
        if only_cur or only_prev:
            label = dim.replace("_", " ")
            where = [f"only in the current period: {', '.join(only_cur)}" if only_cur else "",
                     f"only in the previous period: {', '.join(only_prev)}" if only_prev else ""]
            issues.append(f"Some {label} values appear in one period only "
                          f"({'; '.join(w for w in where if w)}).")

    if issues:
        return ComparisonCheck(kind=CheckKind.POPULATION, status=WARNING,
                               message=" ".join(issues), evidence=evidence)
    scope = inp.kpi.population or "the same filters"
    return ComparisonCheck(kind=CheckKind.POPULATION, status=OK, evidence=evidence,
                           message=f"Same population on both sides: {scope.rstrip('.')}.")


# ---- 3. Unit ------------------------------------------------------------------------
def check_unit(inp: Inputs) -> ComparisonCheck:
    evidence = {"catalog_unit": inp.kpi.unit, "catalog_kpi": inp.kpi.ref}
    if inp.result is not None:
        evidence.update(result_unit=inp.result.unit, result_kpi=inp.result.kpi)
        if inp.result.unit != inp.kpi.unit:
            return ComparisonCheck(kind=CheckKind.UNIT, status=BLOCKING, evidence=evidence,
                                   message=(f"The analysis is in {inp.result.unit} but "
                                            f"{inp.kpi.ref} is defined in {inp.kpi.unit}."))
        if inp.result.kpi != inp.kpi.ref:
            return ComparisonCheck(kind=CheckKind.UNIT, status=WARNING, evidence=evidence,
                                   message=(f"The analysis used {inp.result.kpi} but the catalog "
                                            f"now defines {inp.kpi.ref}."))
    return ComparisonCheck(kind=CheckKind.UNIT, status=OK, evidence=evidence,
                           message=f"Both values are in {inp.kpi.unit} ({inp.kpi.ref}).")


# ---- 4. Scale -----------------------------------------------------------------------
def check_scale(inp: Inputs, rules: Rules) -> ComparisonCheck:
    n_cur, n_prev = len(days_of(inp.request.period)), len(days_of(inp.request.compare_to))
    gap = abs(n_cur - n_prev) / max(n_cur, n_prev)
    evidence = {"days_current": n_cur, "days_previous": n_prev, "length_gap": round(gap, 4),
                "additive_kpi": inp.additive, "expression": inp.kpi.expression}
    if not inp.additive:
        return ComparisonCheck(kind=CheckKind.SCALE, status=OK, evidence=evidence,
                               message=f"{inp.kpi.name} is not a total, so period length does not bias it.")
    if gap > rules.length_blocking:
        status = BLOCKING
    elif gap > rules.length_warning:
        status = WARNING
    else:
        return ComparisonCheck(kind=CheckKind.SCALE, status=OK, evidence=evidence,
                               message=f"Periods of {n_cur} and {n_prev} days: lengths are comparable.")
    return ComparisonCheck(kind=CheckKind.SCALE, status=status, evidence=evidence,
                           message=(f"{inp.kpi.name} is a total and the periods last {n_cur} and "
                                    f"{n_prev} days ({gap:.0%} difference): the longer period "
                                    f"wins partly because it is longer."))


# ---- 5. Grain ------------------------------------------------------------------------
def check_grain(inp: Inputs) -> ComparisonCheck:
    fact = inp.fact
    evidence: dict = {"kpi_grain": inp.kpi.grain, "table": fact.name, "table_grain": fact.grain}
    problems = []
    if inp.kpi.grain != fact.grain:
        problems.append(f"{inp.kpi.ref} expects one row per {inp.kpi.grain} but "
                        f"{fact.name} has one row per {fact.grain}.")
    receipt = next((r for r in inp.receipts.receipts if r.output_table == fact.name), None)
    if receipt:
        evidence.update(rows_before=receipt.rows_before, rows_after=receipt.rows_after,
                        join_keys=receipt.join_keys)
        if receipt.rows_after > receipt.rows_before:
            problems.append(f"Building {fact.name} turned {receipt.rows_before} rows into "
                            f"{receipt.rows_after}: the join on {receipt.join_keys} duplicated rows.")
    dups = inp.duplicate_keys()
    evidence["duplicate_primary_keys"] = dups
    if dups:
        problems.append(f"{dups} rows of {fact.name} share a primary key {fact.primary_key}.")
    if problems:
        return ComparisonCheck(kind=CheckKind.GRAIN, status=BLOCKING, evidence=evidence,
                               message=" ".join(problems))
    return ComparisonCheck(kind=CheckKind.GRAIN, status=OK, evidence=evidence,
                           message=f"Both values come from {fact.name} (one row = one {fact.grain}), "
                                   f"with no duplicated rows.")
