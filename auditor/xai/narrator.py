"""Narrator: turns SHAP numbers into one sentence. Template-based on purpose:
every word is traceable to a number (no LLM, nothing invented).
Dataset-agnostic: labels and units come from the profiling report.
"""
import pandas as pd

from auditor.xai.shap_explainer import RowExplanation
from contracts.i18n import Msg, render

# Words and units come from the profiling report (AnomalyReport.feature_labels / feature_units).
# Without them, a readable fallback is built from the column name: "fee_tnd" -> "Fee tnd".
Labels = dict[str, str]
Units = dict[str, str]

ORDINARY_MARGIN = 1.0     # within 1 split of a typical row = nothing to explain (judgment call)
MIN_SHARE = 0.10          # a feature must carry >= 10% of the push to be named


def label(feature: str, labels: Labels | None = None) -> str:
    if labels and feature in labels:
        return labels[feature]
    return feature.replace("_", " ").strip().capitalize()


def fmt(feature: str, value: float, units: Units | None = None) -> str:
    text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return f"{text} {(units or {}).get(feature, '')}".strip()


POSITION_KEY = {"far above": "word.far_above", "above": "word.above", "far below": "word.far_below",
                "below": "word.below", "close to": "word.close_to", "equal to": "word.equal_to"}


def compare_to_typical(value: float, typical: float) -> str:
    """Position of the value relative to the median of all rows."""
    if typical == 0:
        return "above" if value > 0 else "equal to"
    ratio = value / typical
    if ratio >= 2:
        return "far above"
    if ratio >= 1.3:
        return "above"
    if ratio <= 0.5:
        return "far below"
    if ratio <= 0.77:
        return "below"
    return "close to"


def top_features(exp: RowExplanation, k: int = 2) -> pd.DataFrame:
    """Features that pushed TOWARD anomaly and carry a meaningful share of the push."""
    c = exp.sorted_contributions()
    pos = c[c["shap_value"] > 0]
    total = pos["shap_value"].sum()
    if total == 0:
        return pos.head(0).assign(share=[])
    pos = pos.assign(share=pos["shap_value"] / total)
    return pos[pos["share"] >= MIN_SHARE].head(k)


def is_ordinary(exp: RowExplanation, is_anomaly: bool) -> bool:
    return (not is_anomaly) and exp.splits >= exp.typical_splits - ORDINARY_MARGIN


def narrate_parts(exp: RowExplanation, is_anomaly: bool, medians: pd.Series, k: int = 2,
                  labels: Labels | None = None, units: Units | None = None) -> list[Msg]:
    """The explanation as messages: rendered in any language (contracts/i18n.py)."""
    timing = {"splits": exp.splits, "typical": exp.typical_splits}
    if is_ordinary(exp, is_anomaly):
        return [Msg(key="shap.ordinary", params=timing)]

    top = top_features(exp, k)
    if top.empty:
        return [Msg(key="shap.nothing")]

    reasons: list[Msg] = []
    for r in top.itertuples():
        if reasons:
            reasons.append(Msg(key="word.and"))
        unit = (units or {}).get(r.feature, "")
        reasons.append(Msg(key="shap.reason", params={
            "label": label(r.feature, labels), "value": float(r.value), "typical": float(medians[r.feature]),
            "unit": f" {unit}" if unit else "", "share": float(r.share),
            "position": POSITION_KEY[compare_to_typical(r.value, medians[r.feature])]}))
    key = "shap.flagged" if is_anomaly else "shap.not_flagged"
    return [Msg(key=key, params={"reasons": [m.model_dump() for m in reasons]} | timing)]


def narrate(exp: RowExplanation, is_anomaly: bool, medians: pd.Series, k: int = 2,
            labels: Labels | None = None, units: Units | None = None) -> str:
    """The explanation in English (canonical)."""
    return render(narrate_parts(exp, is_anomaly, medians, k, labels, units))
