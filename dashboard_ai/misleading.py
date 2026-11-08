"""Misleading-visual detector. Complements comparisons/ (BO4-12):

  comparisons/   judges the DATA:   are the two periods comparable?
  this file      judges the PICTURE: does the chart, as drawn, lead to a wrong reading?

Everything here is a warning shown next to the chart, never a silent change.
"""
import pandas as pd

from contracts.comparisons import CheckStatus
from contracts.dashboard import ChartType
from dashboard_ai.messages import t
from dashboard_ai.models import ChartCandidate, IssueKind, VisualIssue
from dashboard_ai.profile import DataProfile, current_rows
from dashboard_ai.rules import Rules


def requested_refused(requested: ChartType, chosen: ChartType, candidates: list[ChartCandidate],
                      lang: str) -> VisualIssue | None:
    cand = next((c for c in candidates if c.chart_type == requested), None)
    if cand is None or cand.eligible:
        return None
    why = " ".join(cand.reasons)
    return VisualIssue(kind=IssueKind.REQUESTED_CHART_REFUSED, status=CheckStatus.WARNING,
                       message=t("issue.requested_refused", lang, asked=t(f"chart.{requested.value}", lang),
                                 chosen=t(f"chart.name.{chosen.value}", lang), why=why),
                       evidence={"asked": requested.value, "chosen": chosen.value, "blockers": cand.reasons})


def missing_time_points(values: list) -> tuple[int, str]:
    s = pd.to_datetime(pd.Series(sorted({str(v) for v in values})), errors="coerce")
    if len(s) < 3 or s.isna().any():
        return 0, ""
    freq = "M" if (s.dt.day == 1).all() else "D"
    full = pd.period_range(s.min(), s.max(), freq=freq)
    have = set(s.dt.to_period(freq))
    missing = [p for p in full if p not in have]
    return len(missing), (str(missing[0]) if missing else "")


def visual_issues(df: pd.DataFrame, p: DataProfile, chosen: ChartType, rules: Rules, lang: str,
                  value_current: float | None, value_previous: float | None) -> list[VisualIssue]:
    issues: list[VisualIssue] = []
    cur = current_rows(df)
    prim = p.primary

    if prim and chosen in (ChartType.BAR, ChartType.PIE):
        by_cat = cur.groupby(prim.name)["value"].sum().sort_values(ascending=False)
        if len(by_cat) >= 2 and p.additive and by_cat.sum() > 0:
            share = float(by_cat.iloc[0] / by_cat.sum())
            if share >= rules.dominant_share:
                issues.append(VisualIssue(kind=IssueKind.DOMINANT_CATEGORY, status=CheckStatus.WARNING,
                              message=t("issue.dominant", lang, cat=by_cat.index[0], share=share),
                              evidence={"category": str(by_cat.index[0]), "share": round(share, 4)}))
        if len(by_cat) >= 2 and by_cat.max() > 0:
            spread = float((by_cat.max() - by_cat.min()) / by_cat.max())
            if spread < rules.small_difference:
                issues.append(VisualIssue(kind=IssueKind.SAME_LEVEL, status=CheckStatus.WARNING,
                              message=t("issue.same_level", lang, spread=spread), evidence={"spread": round(spread, 4)}))

    if prim and chosen == ChartType.LINE:
        n_missing, first = missing_time_points(prim.values)
        if n_missing:
            issues.append(VisualIssue(kind=IssueKind.TIME_GAP, status=CheckStatus.WARNING,
                          message=t("issue.time_gap", lang, n=n_missing, first=first),
                          evidence={"missing": n_missing, "first_missing": first}))

    if value_current is not None and value_previous:
        lo, hi = sorted([abs(value_current), abs(value_previous)])
        if lo > 0 and hi / lo >= rules.base_effect_ratio:
            pct = (value_current - value_previous) / abs(value_previous)
            issues.append(VisualIssue(kind=IssueKind.BASE_EFFECT, status=CheckStatus.WARNING,
                          message=t("issue.base_effect", lang, prev=value_previous, cur=value_current, pct=pct),
                          evidence={"ratio": round(hi / lo, 2), "change_pct": round(pct, 4)}))
    return issues


def mixed_units(metric_units: dict[str, str], lang: str) -> VisualIssue | None:
    """Several KPIs on one dashboard: different units must never share an axis (no dual axis)."""
    units = sorted(set(metric_units.values()))
    if len(units) <= 1:
        return None
    return VisualIssue(kind=IssueKind.MIXED_UNITS, status=CheckStatus.WARNING,
                       message=t("issue.mixed_units", lang, units=", ".join(units)), evidence={"metrics": metric_units})
