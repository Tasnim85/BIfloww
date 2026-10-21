"""Tests for Step 2 — Ambiguity Handler.

Owner: Samar / Malek (Step 2)
"""
from __future__ import annotations

import pytest

from intake.semantic_detection.step2.rule_classifier import ClassificationResult
from intake.semantic_detection.step2.ambiguity_handler import (
    AmbiguityHandler,
    AmbiguityReport,
    ReviewFlag,
    flag_unknown_columns,
    flag_low_confidence,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_result(
    *,
    table: str = "t",
    column: str = "col",
    semantic_type: str = "PRICE",
    semantic_group: str = "FINANCIAL_DATA",
    confidence: float = 0.90,
    match_tier: str = "keyword",
    privacy_hint: str = "NO_DIRECT_PII_INDICATOR",
) -> ClassificationResult:
    return ClassificationResult(
        table=table,
        column=column,
        normalized_key=column.lower(),
        tokens=column.lower().split("_"),
        semantic_group=semantic_group,
        semantic_type=semantic_type,
        confidence=confidence,
        match_tier=match_tier,
        privacy_hint=privacy_hint,
    )


def make_unknown(**kwargs) -> ClassificationResult:
    return make_result(
        semantic_type="UNKNOWN",
        semantic_group="UNKNOWN_DATA",
        confidence=0.00,
        match_tier="unknown",
        **kwargs,
    )


def make_low_conf(**kwargs) -> ClassificationResult:
    return make_result(confidence=0.35, **kwargs)


# ── AmbiguityHandler basic ─────────────────────────────────────────────────────

class TestAmbiguityHandlerBasic:

    @pytest.fixture()
    def handler(self) -> AmbiguityHandler:
        return AmbiguityHandler()

    def test_returns_tuple(self, handler: AmbiguityHandler) -> None:
        results = [make_result()]
        resolved, report = handler.process(results)
        assert isinstance(resolved, list)
        assert isinstance(report, AmbiguityReport)

    def test_clean_results_no_flags(self, handler: AmbiguityHandler) -> None:
        results = [make_result(confidence=0.95), make_result(column="qty", confidence=0.88)]
        _, report = handler.process(results)
        assert report.unknown_count == 0
        assert report.low_confidence_count == 0

    def test_unknown_detected(self, handler: AmbiguityHandler) -> None:
        results = [make_unknown(), make_result()]
        _, report = handler.process(results)
        assert report.unknown_count == 1

    def test_low_confidence_detected(self, handler: AmbiguityHandler) -> None:
        results = [make_low_conf(), make_result()]
        _, report = handler.process(results)
        assert report.low_confidence_count == 1

    def test_unknown_flag_reason(self, handler: AmbiguityHandler) -> None:
        results = [make_unknown(column="weird_col")]
        _, report = handler.process(results)
        flag = next(f for f in report.review_flags if f.column == "weird_col")
        assert flag.reason == "UNKNOWN"

    def test_low_confidence_flag_reason(self, handler: AmbiguityHandler) -> None:
        results = [make_low_conf(column="ambiguous_col")]
        _, report = handler.process(results)
        flag = next(f for f in report.review_flags if f.column == "ambiguous_col")
        assert flag.reason == "LOW_CONFIDENCE"

    def test_total_count_matches(self, handler: AmbiguityHandler) -> None:
        results = [make_result(), make_unknown(), make_low_conf()]
        _, report = handler.process(results)
        assert report.total_columns == 3

    def test_resolved_list_same_length(self, handler: AmbiguityHandler) -> None:
        results = [make_result(), make_unknown(), make_low_conf()]
        resolved, _ = handler.process(results)
        assert len(resolved) == len(results)


# ── Conflict resolution ────────────────────────────────────────────────────────

class TestConflictResolution:

    @pytest.fixture()
    def handler(self) -> AmbiguityHandler:
        return AmbiguityHandler(conflict_gap=0.10)

    def test_clear_winner_by_confidence(self, handler: AmbiguityHandler) -> None:
        """When one candidate has significantly higher confidence, it wins."""
        key = ("t", "col")   # matches make_result() default table="t", column="col"
        winner_res = make_result(confidence=0.92, semantic_type="PRICE")
        loser_res  = make_result(confidence=0.55, semantic_type="NUMERIC_MEASURE")
        multi = {key: [winner_res, loser_res]}
        primary = [winner_res]
        resolved, report = handler.process(primary, multi_results=multi)
        assert report.conflict_count == 1
        assert resolved[0].semantic_type == "PRICE"

    def test_tier_priority_breaks_tie(self, handler: AmbiguityHandler) -> None:
        """When confidence is tied, tier priority decides."""
        key = ("t", "col")
        alias_res   = make_result(confidence=0.80, semantic_type="PRICE",   match_tier="alias")
        keyword_res = make_result(confidence=0.80, semantic_type="REVENUE", match_tier="keyword")
        multi = {key: [alias_res, keyword_res]}
        primary = [alias_res]
        resolved, report = handler.process(primary, multi_results=multi)
        assert report.conflict_count == 1
        # alias beats keyword
        assert resolved[0].semantic_type == "PRICE"

    def test_alphabetical_fallback(self, handler: AmbiguityHandler) -> None:
        """Complete tie resolved deterministically by type_id alphabet."""
        key = ("t", "col")
        rev_res  = make_result(confidence=0.80, semantic_type="REVENUE", match_tier="keyword")
        cost_res = make_result(confidence=0.80, semantic_type="COST",    match_tier="keyword")
        multi = {key: [rev_res, cost_res]}
        primary = [rev_res]
        resolved, report = handler.process(primary, multi_results=multi)
        # alphabetically: COST < REVENUE
        assert resolved[0].semantic_type == "COST"


# ── Report summary ─────────────────────────────────────────────────────────────

class TestReportSummary:

    def test_summary_keys(self) -> None:
        report = AmbiguityReport(
            total_columns=10, unknown_count=2, low_confidence_count=1,
            conflict_count=0,
        )
        s = report.summary()
        assert "total_columns" in s
        assert "unknown" in s
        assert "low_confidence" in s
        assert "pending_review" in s

    def test_to_dict_structure(self) -> None:
        report = AmbiguityReport(
            total_columns=5, unknown_count=1, low_confidence_count=0,
            conflict_count=0,
            review_flags=[ReviewFlag(table="t", column="c", reason="UNKNOWN", confidence=0.0)],
        )
        d = report.to_dict()
        assert "summary" in d
        assert "review_flags" in d
        assert d["review_flags"][0]["reason"] == "UNKNOWN"


# ── Standalone utilities ───────────────────────────────────────────────────────

class TestStandaloneHelpers:

    def test_flag_unknown_columns(self) -> None:
        results = [make_unknown(column="c1"), make_result(column="c2")]
        flags = flag_unknown_columns(results)
        assert len(flags) == 1
        assert flags[0].column == "c1"

    def test_flag_low_confidence(self) -> None:
        results = [make_low_conf(column="c1"), make_result(column="c2", confidence=0.90)]
        flags = flag_low_confidence(results, threshold=0.50)
        assert len(flags) == 1
        assert flags[0].column == "c1"
        assert flags[0].reason == "LOW_CONFIDENCE"

    def test_flag_low_confidence_empty(self) -> None:
        results = [make_result(confidence=0.95)]
        flags = flag_low_confidence(results)
        assert flags == []
