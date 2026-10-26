"""Profile of the data the chart will show: what kind of axes, how many categories, can parts add up?"""
import re
from dataclasses import dataclass, field

import pandas as pd

TEMPORAL_NAMES = {"order_date", "purchase_date", "date", "year", "month", "quarter", "week", "order_month",
                  "order_purchase_date", "day"}
GEO_HINTS = ("_state", "_city", "state", "city", "region", "country", "zip")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}(-\d{2})?")


def is_additive(expression_or_sql: str) -> bool:
    """SUM and COUNT(*) add up across categories. COUNT(DISTINCT ..) and averages do not."""
    s = " ".join(expression_or_sql.upper().split())
    if "COUNT(DISTINCT" in s or "AVG(" in s or "/" in s:
        return False
    return "SUM(" in s or "COUNT(" in s


@dataclass
class DimProfile:
    name: str
    kind: str                 # "temporal" | "geographic" | "categorical"
    cardinality: int
    values: list = field(default_factory=list)


@dataclass
class DataProfile:
    metric: str
    unit: str
    additive: bool
    dims: list[DimProfile]
    has_period: bool
    n_rows: int
    vmin: float
    vmax: float
    has_negative: bool
    total: float

    @property
    def primary(self) -> DimProfile | None:
        return self.dims[0] if self.dims else None

    @property
    def temporal(self) -> bool:
        return bool(self.dims) and self.dims[0].kind == "temporal"


def _kind(name: str, series: pd.Series) -> str:
    if name in TEMPORAL_NAMES or pd.api.types.is_datetime64_any_dtype(series):
        return "temporal"
    sample = series.dropna().astype(str).head(20)
    if len(sample) and all(_DATE_LIKE.match(v) for v in sample):
        return "temporal"
    if any(name == h or name.endswith(h) for h in GEO_HINTS):
        return "geographic"
    return "categorical"


def current_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["period"] == "current"] if "period" in df.columns else df


def build_profile(df: pd.DataFrame, dims: list[str], *, metric: str, unit: str, additive: bool) -> DataProfile:
    cur = current_rows(df)
    dim_profiles = [DimProfile(d, _kind(d, df[d]), int(cur[d].nunique()),
                               sorted(cur[d].dropna().astype(str).unique().tolist())) for d in dims]
    vals = pd.to_numeric(cur["value"], errors="coerce").dropna()
    return DataProfile(metric=metric, unit=unit, additive=additive, dims=dim_profiles,
                       has_period="period" in df.columns, n_rows=len(df),
                       vmin=float(vals.min()) if len(vals) else 0.0, vmax=float(vals.max()) if len(vals) else 0.0,
                       has_negative=bool((vals < 0).any()), total=float(vals.sum()) if len(vals) else 0.0)
