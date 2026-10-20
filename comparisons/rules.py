"""Comparability rules: the thresholds, in ONE place, versioned.

Change a value -> bump RULES_VERSION: the journal records which version decided.
These are judgment calls written down, not laws. The report quotes them as evidence.
"""
from dataclasses import asdict, dataclass

RULES_VERSION = "comparability-rules@1.0"


@dataclass(frozen=True)
class Rules:
    # coverage: an EDGE day (start or end of a period) is incomplete when its volume is
    # below this share of the median daily volume of the OTHER period ...
    min_volume_share: float = 0.60
    # ... or when, for a KPI filtered on a status (e.g. delivered), too few of its rows
    # have reached that status yet ("immature" recent days).
    min_status_share: float = 0.50
    # scale: relative difference of period lengths, for additive KPIs (SUM, COUNT)
    length_warning: float = 0.05     # 28 vs 31 days -> 9.7% -> warning
    length_blocking: float = 0.25    # 7 vs 30 days -> blocking
    # population: difference of status share between the two periods
    status_share_gap: float = 0.05

    def as_evidence(self) -> dict:
        return {"rules_version": RULES_VERSION, **asdict(self)}


DEFAULT = Rules()
