"""Chart rules: every threshold in ONE place, versioned (same idea as comparisons/rules.py).

Change a value -> bump RULES_VERSION: the journal records which version decided.
"""
from dataclasses import asdict, dataclass

RULES_VERSION = "dashboard-rules@1.0"


@dataclass(frozen=True)
class Rules:
    pie_min_slices: int = 2
    pie_max_slices: int = 6          # beyond: angles cannot be compared by eye
    bar_max_categories: int = 15     # beyond: keep the top N (+ "Others" if the KPI is additive)
    line_min_points: int = 3         # a line through 2 points says nothing about a trend
    dominant_share: float = 0.80     # one category above this share crushes the others
    base_effect_ratio: float = 10.0  # current/previous (or inverse) above this -> % change is misleading
    small_difference: float = 0.05   # (max-min)/max below this -> categories are practically equal
    map_enabled: bool = False        # the Streamlit app has no map renderer yet

    def as_evidence(self) -> dict:
        return {"rules_version": RULES_VERSION, **asdict(self)}


DEFAULT = Rules()
