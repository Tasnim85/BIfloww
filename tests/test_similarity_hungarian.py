"""tests/test_similarity_hungarian.py — Validation of the Hungarian alignment upgrade.

Owner  : Malek  (BIFlow Semantic Detection — Etape 0 / BO1-06)
Branch : fix/malek-step2-step3-similarity

Validates that ``intake/similarity.py`` now uses the Hungarian algorithm
(scipy.optimize.linear_sum_assignment) for optimal column-to-column matching,
replacing the previous bidirectional best-match heuristic.

Run with:
    cd BIfloww_integration
    python -m pytest tests/test_similarity_hungarian.py -v
"""
from __future__ import annotations

import pytest


try:
    from intake.similarity import compute_hungarian_similarity, compute_embedding_similarity
    _SIMILARITY_AVAILABLE = True
except ImportError:
    _SIMILARITY_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _SIMILARITY_AVAILABLE,
    reason="intake.similarity not importable -- check PYTHONPATH",
)


# =============================================================================
# compute_hungarian_similarity -- unit tests
# =============================================================================

class TestHungarianSimilarity:
    """Tests for the new compute_hungarian_similarity() function."""

    def test_identical_sets_score_one(self) -> None:
        """Two identical column sets -> score ~ 1.0."""
        cols = ["customer_id", "order_id", "payment_value"]
        result = compute_hungarian_similarity(cols, cols)
        assert "score" in result, "Result must have a 'score' key"
        assert result["score"] >= 0.90, (
            f"Identical sets expected score >= 0.90, got {result['score']}"
        )

    def test_identical_sets_method_starts_hungarian(self) -> None:
        cols = ["customer_id", "order_id"]
        result = compute_hungarian_similarity(cols, cols)
        assert result.get("method", "").startswith("hungarian"), (
            f"Expected method to start with 'hungarian', got {result.get('method')}"
        )

    def test_empty_list_a(self) -> None:
        """Empty list A -> score = 0.0 (no match possible)."""
        result = compute_hungarian_similarity([], ["customer_id"])
        assert result["score"] == 0.0, f"Expected 0.0 for empty A, got {result['score']}"

    def test_empty_list_b(self) -> None:
        """Empty list B -> score = 0.0."""
        result = compute_hungarian_similarity(["customer_id"], [])
        assert result["score"] == 0.0, f"Expected 0.0 for empty B, got {result['score']}"

    def test_both_empty(self) -> None:
        """Both empty -> score = 0.0 (trivial case)."""
        result = compute_hungarian_similarity([], [])
        assert result["score"] == 0.0

    def test_unrelated_sets_low_score(self) -> None:
        """Semantically unrelated column sets -> score < 0.55."""
        result = compute_hungarian_similarity(
            ["sepal_length", "petal_width", "species"],
            ["payment_value", "order_id", "customer_state"],
        )
        assert result["score"] < 0.55, (
            f"Unrelated sets expected score < 0.55, got {result['score']}"
        )

    def test_partial_overlap(self) -> None:
        """Partial overlap: shared column 'customer_id' + unique others -> medium score."""
        result = compute_hungarian_similarity(
            ["customer_id", "order_date", "freight_value"],
            ["customer_id", "product_id", "payment_type"],
        )
        assert result["score"] > 0.15, (
            f"Partial overlap expected score > 0.15, got {result['score']}"
        )

    def test_renamed_synonyms_embeddings(self) -> None:
        """Renamed synonym columns: 'cust_id' vs 'customer_id' -- TF-IDF should give non-zero."""
        result = compute_hungarian_similarity(
            ["cust_id", "buyer_email", "order_date"],
            ["customer_id", "email", "purchase_date"],
        )
        assert result["score"] > 0.05, (
            f"Synonym columns expected score > 0.05, got {result['score']}"
        )

    def test_assignment_key_present(self) -> None:
        """Result must contain an assignment key for audit."""
        cols = ["order_id", "payment_value"]
        result = compute_hungarian_similarity(cols, cols)
        has_assignments = (
            "assignment" in result
            or "assignments" in result
            or "top_assignments" in result
        )
        assert has_assignments, (
            f"Expected assignment key in result, got keys: {list(result.keys())}"
        )

    def test_score_is_normalised(self) -> None:
        """Score must be in [0, 1]."""
        result = compute_hungarian_similarity(
            ["a", "b", "c"],
            ["d", "e"],
        )
        assert 0.0 <= result["score"] <= 1.0, (
            f"Score out of [0,1]: {result['score']}"
        )

    def test_asymmetric_sizes_normalised_by_max(self) -> None:
        """When |A| != |B|, score is normalised by max(|A|, |B|)."""
        result = compute_hungarian_similarity(
            ["customer_id", "order_date", "freight_value"],
            ["customer_id"],
        )
        # Normalised by 3; even perfect match gives 1/3 ~ 0.33
        assert result["score"] <= 0.50, (
            f"3-vs-1 asymmetric: expected <= 0.50 (normalised by 3), got {result['score']}"
        )


# =============================================================================
# compute_embedding_similarity -- backward-compatibility tests
# NOTE: This function returns a float (original API, NOT a dict).
# =============================================================================

class TestEmbeddingSimilarityBackwardCompat:
    """Verify that compute_embedding_similarity() still returns a float (old API unchanged).

    This function is called by tests/test_similarity_embeddings.py and by
    the intake agent run(). Its return type MUST remain float.
    """

    def test_returns_float(self) -> None:
        result = compute_embedding_similarity(["customer_id"], ["customer_id"])
        assert isinstance(result, float), f"Expected float return, got {type(result)}"

    def test_score_in_01_range(self) -> None:
        result = compute_embedding_similarity(
            ["order_id", "product_id"],
            ["order_id", "product_id"],
        )
        assert isinstance(result, float), f"score must be float, got {type(result)}"
        assert 0.0 <= result <= 1.0, f"score out of [0,1]: {result}"

    def test_identical_columns_high_score(self) -> None:
        result = compute_embedding_similarity(
            ["order_id", "customer_id", "payment_value"],
            ["order_id", "customer_id", "payment_value"],
        )
        assert result >= 0.80, (
            f"Identical columns: expected score >= 0.80, got {result}"
        )

    def test_empty_set_returns_zero(self) -> None:
        result = compute_embedding_similarity([], ["customer_id"])
        assert result == 0.0, f"Empty cols_a: expected 0.0, got {result}"

    def test_different_columns_lower_score(self) -> None:
        same = compute_embedding_similarity(["customer_id"], ["customer_id"])
        diff = compute_embedding_similarity(["customer_id"], ["freight_value"])
        assert same > diff, (
            f"Identical match ({same}) should score higher than different ({diff})"
        )

    def test_hungarian_internally_consistent(self) -> None:
        """compute_embedding_similarity internally uses compute_hungarian_similarity.
        Both must give a high score for identical column sets."""
        cols = ["order_id", "customer_id", "payment_value"]
        emb_score = compute_embedding_similarity(cols, cols)
        hung_result = compute_hungarian_similarity(cols, cols)
        assert emb_score >= 0.90, f"embedding_similarity: expected >=0.90, got {emb_score}"
        assert hung_result["score"] >= 0.90, (
            f"hungarian: expected >=0.90, got {hung_result['score']}"
        )


# =============================================================================
# Hungarian vs Bidirectional best-match -- comparative test
# =============================================================================

class TestHungarianVsBidirectional:
    """Demonstrate that Hungarian produces optimal (Pareto-efficient) assignments.

    The Hungarian algorithm minimises total cost on the full assignment matrix,
    guaranteed globally optimal. A bidirectional best-match heuristic can
    produce sub-optimal results when columns compete for the same partner.
    """

    def test_no_double_assignment(self) -> None:
        """Each column in A is assigned to at most one column in B.

        Bidirectional best-match can assign two A-cols to the same B-col.
        The Hungarian assignment must be injective.
        """
        result = compute_hungarian_similarity(
            ["customer_id", "client_id", "user_id"],
            ["customer_id", "order_id"],
        )
        top = (
            result.get("top_assignments")
            or result.get("assignments")
            or result.get("assignment")
            or []
        )
        if top:
            b_assigned = [
                pair[1] if isinstance(pair, (list, tuple)) else pair.get("col_b")
                for pair in top
            ]
            b_assigned_clean = [b for b in b_assigned if b is not None]
            # Each B column appears at most once in the assignment
            assert len(b_assigned_clean) == len(set(b_assigned_clean)), (
                "Hungarian assignment is not injective -- double B assignment detected!"
            )
