"""Everything this step reads, in one object. SQL lives here.

Numbers always come from SQL on the warehouse, with the KPI definition of the
catalog (SEM supplies definitions). Nothing is computed by the LLM.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

from contracts.analysis import AnalysisResult
from contracts.common import Period, load
from contracts.quality import CoverageProfile, DayCoverage, TableCoverage
from contracts.semantic import AnalysisRequest, KpiCatalog, KpiDefinition, load_yaml
from contracts.warehouse import TransformationReceipts, WarehouseManifest, WarehouseTable

_STATUS_FILTER = re.compile(r"^\s*(\w+)\s*=\s*'([^']+)'\s*$")


def days_of(p: Period) -> list[str]:
    start, end = date.fromisoformat(p.start), date.fromisoformat(p.end)
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


@dataclass
class Inputs:
    request: AnalysisRequest
    result: AnalysisResult | None
    catalog: KpiCatalog
    kpi: KpiDefinition
    coverage: CoverageProfile
    manifest: WarehouseManifest
    receipts: TransformationReceipts
    warehouse: Path

    # ---- lookups ------------------------------------------------------------------
    @property
    def fact(self) -> WarehouseTable:
        return next(t for t in self.manifest.tables if t.name == self.kpi.table)

    def coverage_table(self) -> TableCoverage:
        """The profiled table that holds the KPI's dates (orders for Olist)."""
        return self.coverage.tables[0]

    def coverage_days(self, p: Period) -> list[DayCoverage]:
        """One entry per day of the period; days absent from the profile count as 0 rows."""
        known = {d.date: d for d in self.coverage_table().days}
        return [known.get(d, DayCoverage(date=d, rows=0)) for d in days_of(p)]

    def status_filter(self) -> tuple[str, str] | None:
        """('order_status', 'delivered') if the KPI keeps only one status, else None."""
        status_col = self.coverage_table().status_column
        for f in self.kpi.filters:
            m = _STATUS_FILTER.match(f)
            if m and m.group(1) == status_col:
                return m.group(1), m.group(2)
        return None

    @property
    def additive(self) -> bool:
        """SUM and COUNT grow with the length of the period; averages and ratios do not."""
        return self.kpi.expression.strip().upper().startswith(("SUM(", "COUNT("))

    # ---- SQL ------------------------------------------------------------------------
    def _connect(self):
        return duckdb.connect(str(self.warehouse), read_only=True)

    def _where(self) -> str:
        parts = [f"{self.kpi.date_column} BETWEEN ? AND ?", *self.kpi.filters, *self.request.filters]
        return " AND ".join(f"({p})" for p in parts)

    def kpi_value(self, p: Period) -> float:
        sql = f"SELECT {self.kpi.expression} FROM {self.kpi.table} WHERE {self._where()}"
        with self._connect() as con:
            v = con.execute(sql, [p.start, p.end]).fetchone()[0]
        return round(float(v or 0.0), 2)

    def dimension_values(self, dim_name: str, p: Period) -> set[str]:
        dim = next(d for d in self.catalog.dimensions if d.name == dim_name)
        if dim.table == self.kpi.table:
            sql = f"SELECT DISTINCT {dim.column} FROM {self.kpi.table} WHERE {self._where()}"
        else:
            key = next(k for k in self.fact.columns if k in _keys_of(self.manifest, dim.table))
            sql = (f"SELECT DISTINCT d.{dim.column} FROM {self.kpi.table} "
                   f"JOIN {dim.table} d USING ({key}) WHERE {self._where()}")
        with self._connect() as con:
            return {str(r[0]) for r in con.execute(sql, [p.start, p.end]).fetchall()}

    def duplicate_keys(self) -> int:
        pk = ", ".join(self.fact.primary_key)
        sql = f"SELECT COUNT(*) - COUNT(DISTINCT ({pk})) FROM {self.kpi.table}"
        with self._connect() as con:
            return int(con.execute(sql).fetchone()[0])


def _keys_of(manifest: WarehouseManifest, table: str) -> list[str]:
    return next(t.primary_key for t in manifest.tables if t.name == table)


def load_inputs(paths: dict[str, Path]) -> Inputs:
    """paths = ctx.inputs. The analysis result is optional (recomputed anyway)."""
    request = load(AnalysisRequest, paths["request"])
    catalog = load_yaml(KpiCatalog, paths["catalog"])
    result_path = Path(paths["result"])
    return Inputs(
        request=request,
        result=load(AnalysisResult, result_path) if result_path.exists() else None,
        catalog=catalog, kpi=catalog.kpi(request.metric),
        coverage=load(CoverageProfile, paths["coverage"]),
        manifest=load(WarehouseManifest, paths["manifest"]),
        receipts=load(TransformationReceipts, paths["receipts"]),
        warehouse=Path(paths["warehouse"]),
    )
