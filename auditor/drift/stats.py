"""Pure statistical tools (from the BO3 prototype): PSI, KS test, control limits.

Change from the prototype: no p-chart for rates. On real Olist months the anomaly
rate varies far more than binomial noise (0.69% to 1.40% with nothing planted:
"overdispersion"), so a p-chart raised false alarms. Every metric now uses an
individuals chart: limits from the REAL month-to-month variation of the reference.
"""
import numpy as np
from scipy import stats as sps

PSI_WATCH = 0.10    # industry convention, not a law
PSI_DRIFT = 0.25
KS_ALPHA = 0.01


def psi(reference, current, bins: int = 10) -> float:
    """Population Stability Index. Bins are built on the REFERENCE quantiles."""
    reference = np.asarray(reference, float)
    current = np.asarray(current, float)
    edges = np.quantile(reference, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    edges = np.unique(edges)                       # discrete data can repeat quantiles
    ref_pct = np.histogram(reference, bins=edges)[0] / len(reference)
    cur_pct = np.histogram(current, bins=edges)[0] / len(current)
    ref_pct = np.clip(ref_pct, 1e-4, None)         # avoid log(0)
    cur_pct = np.clip(cur_pct, 1e-4, None)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def ks_test(reference, current) -> tuple[float, float]:
    """Returns (KS statistic D, p-value)."""
    r = sps.ks_2samp(reference, current)
    return float(r.statistic), float(r.pvalue)


def control_limits(values, k: float = 3.0, min_rel_sigma: float = 0.0) -> tuple[float, float, float]:
    """Mean +/- k sigma over the reference values. Returns (center, lower, upper).

    sigma has a floor (min_rel_sigma * |mean|): with few reference months it is
    poorly estimated, and some metrics drift slowly for business reasons (the share
    of delivered orders rose from 97% to 99% in spring 2018). An explicit assumption.
    """
    values = np.asarray(values, float)
    center = float(values.mean())
    sigma = max(float(values.std(ddof=1)) if len(values) > 1 else 0.0, min_rel_sigma * abs(center))
    return center, center - k * sigma, center + k * sigma
