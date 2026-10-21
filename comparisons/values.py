"""The KPI for the two periods, by one dimension, straight from the warehouse.

What the dashboard shows AFTER the BO4-12 decision: dashboard_periods() says which periods to use
(the accepted fix, or the periods as asked), kpi_by_dimension() computes the values in SQL from
the catalog definition. Nothing here is specific to a dataset. Used by the API and the Streamlit
mock-up; Samar's dashboard can call it too.
"""
from pathlib import Path

import duckdb
from pydantic import BaseModel

from contracts.common import Period
from contracts.comparisons import CheckStatus, ComparisonReport, UserDecision
from contracts.semantic import AnalysisRequest, KpiCatalog
from contracts.warehouse import WarehouseManifest


def dashboard_periods(report: ComparisonReport | None,
                      request: AnalysisRequest) -> tuple[tuple[Period, Period | None] | None, str]:
    """(period, compare_to) the dashboard must use, and why:
        "fix:<method>"      the user accepted a fix
        "as_asked"          valid comparison (or nothing to compare)
        "as_asked_by_user"  blocked, but the user chose to keep the comparison as asked
        "waiting_for_user"  blocked and not decided yet: show nothing (periods = None)
    """
    asked = (request.period, request.compare_to)
    if request.compare_to is None or report is None or not report.has_comparison:
        return asked, "as_asked"
    fixes = ([report.proposed_fix] if report.proposed_fix else []) + report.alternatives
    if report.user_decision == UserDecision.ACCEPTED and report.chosen_fix:
        f = next(x for x in fixes if x.method == report.chosen_fix)
        return (f.period, f.compare_to), f"fix:{f.method.value}"
    if report.user_decision == UserDecision.REJECTED:
        return asked, "as_asked_by_user"
    if any(c.status == CheckStatus.BLOCKING for c in report.checks):
        return None, "waiting_for_user"
    return asked, "as_asked"


class Row(BaseModel):
    label: str
    current: float
    previous: float | None = None


class KpiBreakdown(BaseModel):
    kpi: str                          # "Revenue@2.0"
    unit: str
    dimension: str | None             # None = a single total
    period: Period
    compare_to: Period | None
    periods_source: str               # see dashboard_periods()
    total_current: float
    total_previous: float | None
    change_pct: float | None
    rows: list[Row]                   # sorted by current value, largest first


def kpi_by_dimension(warehouse: Path, manifest: WarehouseManifest, catalog: KpiCatalog,
                     request: AnalysisRequest, period: Period, compare_to: Period | None,
                     periods_source: str = "as_asked", limit: int | None = None) -> KpiBreakdown:
    kpi = catalog.kpi(request.metric)
    where = " AND ".join(f"({f})" for f in kpi.filters + request.filters) or "TRUE"
    dim = next((d for d in catalog.dimensions if d.name in request.dimensions), None)
    if dim is None:
        group, join = "'total'", ""
    elif dim.table == kpi.table:
        group, join = f"f.{dim.column}", ""
    else:
        keys = next(t.primary_key for t in manifest.tables if t.name == dim.table)
        group, join = f"d.{dim.column}", f"JOIN {dim.table} d USING ({', '.join(keys)})"
    sql = (f"SELECT CAST({group} AS VARCHAR) AS label, {kpi.expression} AS value FROM {kpi.table} f "
           f"{join} WHERE {where} AND f.{kpi.date_column} BETWEEN ? AND ? GROUP BY 1")
    with duckdb.connect(str(warehouse), read_only=True) as con:
        cur = {r[0]: float(r[1] or 0) for r in con.execute(sql, [period.start, period.end]).fetchall()}
        prev = ({r[0]: float(r[1] or 0) for r in con.execute(sql, [compare_to.start, compare_to.end]).fetchall()}
                if compare_to else None)
    labels = sorted(set(cur) | set(prev or {}), key=lambda k: -cur.get(k, 0.0))
    rows = [Row(label=str(k), current=round(cur.get(k, 0.0), 2),
                previous=round(prev.get(k, 0.0), 2) if prev is not None else None) for k in labels]
    t_cur = round(sum(cur.values()), 2)
    t_prev = round(sum(prev.values()), 2) if prev is not None else None
    return KpiBreakdown(kpi=kpi.ref, unit=kpi.unit, dimension=dim.name if dim else None, period=period,
                        compare_to=compare_to, periods_source=periods_source, total_current=t_cur,
                        total_previous=t_prev, change_pct=(t_cur / t_prev - 1) if t_prev else None,
                        rows=rows[:limit] if limit else rows)
