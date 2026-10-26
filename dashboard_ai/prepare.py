"""Prepare the data file each chart will read, so the app only has to draw it."""
import pandas as pd

from contracts.dashboard import ChartType
from dashboard_ai.messages import t
from dashboard_ai.models import IssueKind, VisualIssue
from contracts.comparisons import CheckStatus
from dashboard_ai.profile import DataProfile, current_rows
from dashboard_ai.rules import Rules


def prepare(df: pd.DataFrame, chosen: ChartType, p: DataProfile, rules: Rules, lang: str,
            comparison_shown: bool) -> tuple[pd.DataFrame, str | None, str | None, list[VisualIssue]]:
    """Returns (data, x, color, issues). y is always "value"."""
    issues: list[VisualIssue] = []
    d = df.copy() if comparison_shown else current_rows(df).copy()
    if not comparison_shown and "period" in d.columns:
        d = d.drop(columns="period")
    dims = [x.name for x in p.dims]
    color = "period" if comparison_shown else (dims[1] if len(dims) > 1 else None)

    if chosen == ChartType.BAR:
        dim = dims[0]
        order = current_rows(df).groupby(dim)["value"].sum().sort_values(ascending=False)
        if len(order) > rules.bar_max_categories:
            keep = list(order.index[:rules.bar_max_categories])
            rest = d[~d[dim].isin(keep)]
            d = d[d[dim].isin(keep)]
            if p.additive and len(rest):
                group_cols = [c for c in d.columns if c not in (dim, "value")]
                other = (rest.groupby(group_cols, dropna=False)["value"].sum().reset_index() if group_cols
                         else pd.DataFrame({"value": [rest["value"].sum()]}))
                other[dim] = t("others", lang)
                d = pd.concat([d, other[d.columns]], ignore_index=True)
            issues.append(VisualIssue(kind=IssueKind.TOO_MANY_CATEGORIES, status=CheckStatus.WARNING,
                          message=t("issue.top_n", lang, n=len(order), top=rules.bar_max_categories,
                                    others=t("issue.top_n_others", lang) if p.additive else ""),
                          evidence={"categories": int(len(order)), "kept": rules.bar_max_categories}))
        rank = {k: i for i, k in enumerate(order.index)}
        d = d.assign(_o=d[dim].map(rank).fillna(len(rank))).sort_values("_o").drop(columns="_o")
        return d.reset_index(drop=True), dim, color, issues

    if chosen == ChartType.LINE:
        dim = dims[0]
        d = d.sort_values([dim] + (["period"] if comparison_shown else []))
        x = dim
        if comparison_shown:
            sets = [set(g[dim].astype(str)) for _, g in d.groupby("period")]
            if len(sets) == 2 and not (sets[0] & sets[1]):      # e.g. Aug vs Jul: months never match
                d["position"] = d.groupby("period")[dim].rank(method="dense").astype(int)
                x = "position"
        return d.reset_index(drop=True), x, color, issues

    if chosen == ChartType.PIE:
        dim = dims[0]
        return d.sort_values("value", ascending=False).reset_index(drop=True), dim, None, issues

    if chosen == ChartType.KPI_CARD:
        return pd.DataFrame({"value": [p.total]}), None, None, issues

    return d.reset_index(drop=True), (dims[0] if dims else None), color, issues     # table / map
