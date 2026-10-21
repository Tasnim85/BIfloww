"""intake/semantic_detection/step2/ambiguity_handler.py ÔÇö Step 2 Unknown & Ambiguity Handler.

Owner  : Samar / Malek  (Step 2)
Purpose: Post-process a list of :class:`ClassificationResult` objects to:
  - Identify truly unknown columns.
  - Detect rule conflicts (same column, multiple matching rules with different types).
  - Resolve conflicts using priority rules.
  - Flag columns that require human review.
  - Generate a structured :class:`AmbiguityReport`.

The handler does NOT modify the input results in-place; it returns new resolved
results and a separate report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intake.semantic_detection.step2.rule_classifier import ClassificationResult


# ÔöÇÔöÇ Thresholds ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

# Columns with confidence below this value are flagged for review
_LOW_CONFIDENCE_THRESHOLD = 0.50

# Confidence gap below which two competing results are considered "conflicting"
_CONFLICT_GAP = 0.10


# ÔöÇÔöÇ Data models ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

@dataclass
class ConflictDetail:
    """Two competing classifications for the same column."""
    winner: ClassificationResult
    loser: ClassificationResult
    reason: str          # human-readable explanation of why winner was chosen


@dataclass
class ReviewFlag:
    """A column that requires human validation."""
    table: str
    column: str
    reason: str          # "UNKNOWN" | "LOW_CONFIDENCE" | "CONFLICT_UNRESOLVED"
    confidence: float
    candidates: list[str] = field(default_factory=list)   # candidate type_ids if ambiguous


@dataclass
class AmbiguityReport:
    """Full ambiguity / review report for one classification run."""
    total_columns: int
    unknown_count: int
    low_confidence_count: int
    conflict_count: int
    review_flags: list[ReviewFlag] = field(default_factory=list)
    resolved_conflicts: list[ConflictDetail] = field(default_factory=list)
    unresolved_conflicts: list[tuple[str, str]] = field(default_factory=list)  # (table, column)

    def summary(self) -> dict[str, Any]:
        return {
            "total_columns": self.total_columns,
            "unknown": self.unknown_count,
            "low_confidence": self.low_confidence_count,
            "conflicts_resolved": self.conflict_count,
            "pending_review": len(self.review_flags),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "review_flags": [
                {
                    "table": f.table,
                    "column": f.column,
                    "reason": f.reason,
                    "confidence": f.confidence,
                    "candidates": f.candidates,
                }
                for f in self.review_flags
            ],
            "resolved_conflicts": [
                {
                    "table": c.winner.table,
                    "column": c.winner.column,
                    "winner_type": c.winner.semantic_type,
                    "loser_type": c.loser.semantic_type,
                    "reason": c.reason,
                }
                for c in self.resolved_conflicts
            ],
        }


# ÔöÇÔöÇ Handler ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

class AmbiguityHandler:
    """Detect and resolve unknown/ambiguous classification results.

    Args:
        low_confidence_threshold: Confidence below which a column is flagged.
        conflict_gap: Max confidence gap for two results to be considered conflicting.
        priority_tier_order: Resolution priority when confidence is tied.
            Higher-priority tiers are listed first.
    """

    _DEFAULT_TIER_PRIORITY = ["alias", "keyword", "pattern", "context", "unknown"]

    def __init__(
        self,
        *,
        low_confidence_threshold: float = _LOW_CONFIDENCE_THRESHOLD,
        conflict_gap: float = _CONFLICT_GAP,
        priority_tier_order: list[str] | None = None,
    ) -> None:
        self._low_conf = low_confidence_threshold
        self._conflict_gap = conflict_gap
        self._tier_order = priority_tier_order or self._DEFAULT_TIER_PRIORITY

    # ÔöÇÔöÇ Public API ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

    def process(
        self,
        results: list[ClassificationResult],
        *,
        multi_results: dict[tuple[str, str], list[ClassificationResult]] | None = None,
    ) -> tuple[list[ClassificationResult], AmbiguityReport]:
        """Analyse results for unknowns, conflicts, and low-confidence cases.

        Args:
            results: Primary classification results (one per column).
            multi_results: Optional dict mapping (table, column) to a list of
                competing classifications (for conflict detection).

        Returns:
            Tuple of (resolved_results, AmbiguityReport).
        """
        resolved: list[ClassificationResult] = []
        review_flags: list[ReviewFlag] = []
        resolved_conflicts: list[ConflictDetail] = []
        unresolved: list[tuple[str, str]] = []
        unknown_count = 0
        low_conf_count = 0
        conflict_count = 0

        for res in results:
            key = (res.table, res.column)
            competing = (multi_results or {}).get(key, [])

            # ÔöÇÔöÇ Conflict resolution ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
            if len(competing) > 1:
                winner, detail = self._resolve_conflict(competing)
                if detail:
                    resolved_conflicts.append(detail)
                    conflict_count += 1
                    res = winner
                    if not detail.reason.startswith("clear_winner"):
                        # Truly ambiguous ÔÇö flag for review
                        unresolved.append(key)
                        review_flags.append(ReviewFlag(
                            table=res.table,
                            column=res.column,
                            reason="CONFLICT_UNRESOLVED",
                            confidence=res.confidence,
                            candidates=[r.semantic_type for r in competing],
                        ))
            # ÔöÇÔöÇ Unknown detection ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
            if res.is_unknown:
                unknown_count += 1
                review_flags.append(ReviewFlag(
                    table=res.table,
                    column=res.column,
                    reason="UNKNOWN",
                    confidence=0.00,
                ))
            # ÔöÇÔöÇ Low-confidence detection ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
            elif res.is_low_confidence:
                low_conf_count += 1
                review_flags.append(ReviewFlag(
                    table=res.table,
                    column=res.column,
                    reason="LOW_CONFIDENCE",
                    confidence=res.confidence,
                    candidates=[res.semantic_type],
                ))

            resolved.append(res)

        report = AmbiguityReport(
            total_columns=len(results),
            unknown_count=unknown_count,
            low_confidence_count=low_conf_count,
            conflict_count=conflict_count,
            review_flags=review_flags,
            resolved_conflicts=resolved_conflicts,
            unresolved_conflicts=unresolved,
        )
        return resolved, report

    # ÔöÇÔöÇ Private: conflict resolution ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

    def _resolve_conflict(
        self,
        candidates: list[ClassificationResult],
    ) -> tuple[ClassificationResult, ConflictDetail | None]:
        """Pick the best result among competing candidates.

        Resolution strategy (in order):
          1. Highest confidence wins outright if gap > _conflict_gap.
          2. If tied within gap, higher-priority tier wins.
          3. If still tied, lower alphabetical type_id (deterministic fallback).
        """
        if len(candidates) == 1:
            return candidates[0], None

        candidates = sorted(candidates, key=lambda r: -r.confidence)
        best = candidates[0]
        second = candidates[1]

        # Clear winner by confidence
        if best.confidence - second.confidence > self._conflict_gap:
            detail = ConflictDetail(
                winner=best,
                loser=second,
                reason=f"clear_winner:confidence_gap={best.confidence - second.confidence:.2f}",
            )
            return best, detail

        # Tied ÔÇö resolve by tier priority
        best_tier_rank = self._tier_rank(best.match_tier)
        second_tier_rank = self._tier_rank(second.match_tier)
        if best_tier_rank < second_tier_rank:
            detail = ConflictDetail(
                winner=best, loser=second,
                reason=f"tier_priority:{best.match_tier}>{second.match_tier}",
            )
            return best, detail
        if second_tier_rank < best_tier_rank:
            detail = ConflictDetail(
                winner=second, loser=best,
                reason=f"tier_priority:{second.match_tier}>{best.match_tier}",
            )
            return second, detail

        # Still tied ÔÇö deterministic alphabetical fallback
        winner = min(candidates, key=lambda r: r.semantic_type)
        loser  = max(candidates, key=lambda r: r.semantic_type)
        detail = ConflictDetail(
            winner=winner, loser=loser,
            reason="alphabetical_fallback:ambiguous_tie",
        )
        return winner, detail

    def _tier_rank(self, tier: str) -> int:
        try:
            return self._tier_order.index(tier)
        except ValueError:
            return len(self._tier_order)


# ÔöÇÔöÇ Standalone helper ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

def flag_unknown_columns(
    results: list[ClassificationResult],
) -> list[ReviewFlag]:
    """Quick utility ÔÇö return only the UNKNOWN review flags from a result list."""
    return [
        ReviewFlag(
            table=r.table,
            column=r.column,
            reason="UNKNOWN",
            confidence=0.0,
        )
        for r in results
        if r.is_unknown
    ]


def flag_low_confidence(
    results: list[ClassificationResult],
    threshold: float = _LOW_CONFIDENCE_THRESHOLD,
) -> list[ReviewFlag]:
    """Quick utility ÔÇö return only the LOW_CONFIDENCE flags from a result list."""
    return [
        ReviewFlag(
            table=r.table,
            column=r.column,
            reason="LOW_CONFIDENCE",
            confidence=r.confidence,
            candidates=[r.semantic_type],
        )
        for r in results
        if not r.is_unknown and r.confidence < threshold
    ]
