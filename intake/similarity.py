"""intake/similarity.py — Step 0: dataset similarity detection (Malek — BO1-06).

Compares uploaded column names against known datasets (e.g. Olist sample)
using both embedding-based cosine similarity (BO1-06) and lexical Jaccard overlap.

BO1-06 Phase 2 — Hungarian Algorithm (Linear Sum Assignment)
-------------------------------------------------------------
The optimal bijective column alignment between two column-name sets is computed
via ``scipy.optimize.linear_sum_assignment`` applied to the pairwise cosine
similarity matrix of column-name embeddings.

This gives a one-to-one assignment maximising the total match quality, rather
than simply averaging all best-match scores, which would double-count shared
vocabulary.  The Hungarian method is the same algorithm used in the local
prototype ``BO1/biflow/core/embeddings.py`` (lines 9, 68).

The overall dataset similarity score is::

    S = sum(sim[i, assignment[i]] for i in rows) / max(|A|, |B|)

where the denominator penalises schema width mismatches.

References
----------
* Kuhn (1955) "The Hungarian Method for the assignment problem."
* STEP2_INTEGRATION_PROPOSAL.md §Unification Step 0 + Step 4.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import load, save
from contracts.intake import DatasetMatch, SimilarityReport, Upload
from contracts.proposals.semantic_contracts import (
    RelationshipType,
    SemanticMatch,
    SemanticMatchesReport,
)

logger = logging.getLogger(__name__)

# Known dataset fingerprints (column name sets).
_KNOWN_DATASETS: dict[str, set[str]] = {
    "olist": {
        "order_id", "customer_id", "order_status", "order_purchase_timestamp",
        "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date",
        "customer_unique_id", "customer_zip_code_prefix", "customer_city",
        "customer_state", "product_id", "seller_id", "price", "freight_value",
        "payment_type", "payment_installments", "payment_value", "review_score",
        "review_comment_message", "product_category_name", "product_weight_g",
        "geolocation_lat", "geolocation_lng",
    },
}

_PLAYBOOKS: dict[str, str] = {
    "olist": "olist@1.3",
}

THRESHOLD = 0.4   # Match threshold (Jaccard or Embedding)

# Cache for sentence-transformers model
_MODEL_INSTANCE: Any = None
_MODEL_TRIED: bool = False


def _get_embedding_model() -> Any:
    """Lazy-load the SentenceTransformer model (offline/cached if available)."""
    global _MODEL_INSTANCE, _MODEL_TRIED
    if _MODEL_TRIED:
        return _MODEL_INSTANCE
    _MODEL_TRIED = True
    try:
        from sentence_transformers import SentenceTransformer
        _MODEL_INSTANCE = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as exc:
        logger.warning("SentenceTransformer all-MiniLM-L6-v2 not available: %s", exc)
        _MODEL_INSTANCE = None
    return _MODEL_INSTANCE


def _jaccard(a: set[str], b: set[str]) -> float:
    """Lexical Jaccard similarity between two sets of column names."""
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _normalize(name: str) -> str:
    """Normalize a column name for comparison."""
    return name.lower().replace("_", " ").strip()


# ── Hungarian-based similarity (BO1-06 Phase 2) ─────────────────────────────

def compute_hungarian_similarity(
    cols_a: list[str] | set[str],
    cols_b: list[str] | set[str],
) -> dict[str, Any]:
    """Compute optimal bijective column alignment via the Hungarian algorithm.

    Uses the pairwise cosine similarity matrix of column-name embeddings as the
    cost matrix, then calls ``scipy.optimize.linear_sum_assignment`` to find the
    assignment of maximum total similarity.

    Args:
        cols_a: Column names from dataset A.
        cols_b: Column names from dataset B.

    Returns:
        A dict with keys:
          ``score``        — overall similarity ∈ [0, 1].
          ``assignment``   — list of (col_a, col_b, sim_score) triples.
          ``method``       — ``"hungarian_embedding"`` or ``"hungarian_tfidf"``.
          ``warning``      — str or None, set when the model was unavailable.
    """
    import numpy as np

    list_a = [_normalize(c) for c in cols_a if c]
    list_b = [_normalize(c) for c in cols_b if c]
    n_a, n_b = len(list_a), len(list_b)

    if n_a == 0 or n_b == 0:
        return {"score": 0.0, "assignment": [], "method": "empty", "warning": None}

    # Build pairwise similarity matrix
    model = _get_embedding_model()
    sim_matrix: np.ndarray
    method: str
    warning: str | None = None

    if model is not None:
        try:
            emb_a = model.encode(list_a, convert_to_numpy=True, normalize_embeddings=True)
            emb_b = model.encode(list_b, convert_to_numpy=True, normalize_embeddings=True)
            sim_matrix = np.clip(np.dot(emb_a, emb_b.T), 0.0, 1.0)
            method = "hungarian_embedding"
        except Exception as exc:
            warning = f"Embedding failed ({exc}); falling back to TF-IDF."
            model = None

    if model is None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity as sk_cosine
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
            all_terms = list(set(list_a + list_b))
            vec.fit(all_terms)
            tf_a = vec.transform(list_a).toarray()
            tf_b = vec.transform(list_b).toarray()
            sim_matrix = np.clip(sk_cosine(tf_a, tf_b), 0.0, 1.0)
            method = "hungarian_tfidf"
        except Exception as exc2:
            # Ultimate fallback: identity matching on normalised names
            set_a, set_b = set(list_a), set(list_b)
            overlap = len(set_a & set_b) / max(len(set_a | set_b), 1)
            return {
                "score": float(overlap),
                "assignment": [],
                "method": "jaccard_fallback",
                "warning": f"TF-IDF also failed ({exc2}); Jaccard used.",
            }

    # Apply Hungarian algorithm (maximise total similarity)
    from scipy.optimize import linear_sum_assignment

    row_idx, col_idx = linear_sum_assignment(-sim_matrix)  # negate → maximise

    # Build named assignment list
    orig_a = list(cols_a) if not isinstance(cols_a, list) else cols_a
    orig_b = list(cols_b) if not isinstance(cols_b, list) else cols_b
    assignment = [
        {
            "col_a": orig_a[i] if i < len(orig_a) else list_a[i],
            "col_b": orig_b[j] if j < len(orig_b) else list_b[j],
            "sim": round(float(sim_matrix[i, j]), 4),
        }
        for i, j in zip(row_idx, col_idx)
    ]

    # Score = sum of matched similarities / max schema width (penalise width mismatch)
    total_sim = float(sum(sim_matrix[i, j] for i, j in zip(row_idx, col_idx)))
    score = round(total_sim / max(n_a, n_b), 4)
    score = max(0.0, min(1.0, score))

    return {
        "score": score,
        "assignment": assignment,
        "method": method,
        "warning": warning,
    }


def compute_embedding_similarity(cols_a: list[str] | set[str], cols_b: list[str] | set[str]) -> float:
    """Compute semantic vector similarity between two column sets using embeddings.

    Uses ``compute_hungarian_similarity`` for an optimal bijective alignment, then
    falls back to bidirectional-best-match average if scipy is unavailable.

    Args:
        cols_a: Column names from dataset A.
        cols_b: Column names from dataset B.

    Returns:
        Similarity score ∈ [0, 1].
    """
    list_a = [_normalize(c) for c in cols_a if c]
    list_b = [_normalize(c) for c in cols_b if c]
    if not list_a or not list_b:
        return 0.0

    # Identical sets check
    if set(list_a) == set(list_b):
        return 1.0

    # Try Hungarian first (optimal bijective alignment)
    try:
        result = compute_hungarian_similarity(cols_a, cols_b)
        if result["method"] not in ("empty", "jaccard_fallback"):
            return result["score"]
        if result["method"] == "jaccard_fallback":
            return result["score"]
    except Exception as exc:
        logger.warning("Hungarian similarity failed, falling back to bidirectional: %s", exc)

    # Fallback: bidirectional best-match average (original implementation)
    model = _get_embedding_model()
    if model is not None:
        try:
            import numpy as np
            emb_a = model.encode(list_a, convert_to_numpy=True, normalize_embeddings=True)
            emb_b = model.encode(list_b, convert_to_numpy=True, normalize_embeddings=True)
            sim_matrix = np.dot(emb_a, emb_b.T)
            max_a_to_b = sim_matrix.max(axis=1).mean()
            max_b_to_a = sim_matrix.max(axis=0).mean()
            score = float((max_a_to_b + max_b_to_a) / 2.0)
            return max(0.0, min(1.0, round(score, 4)))
        except Exception as exc:
            logger.warning("Embedding cosine computation failed, falling back: %s", exc)

    # Fallback: char n-gram TF-IDF cosine
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        all_terms = list(set(list_a + list_b))
        vec.fit(all_terms)
        tf_a = vec.transform(list_a)
        tf_b = vec.transform(list_b)
        sim = cosine_similarity(tf_a, tf_b)
        score = float((sim.max(axis=1).mean() + sim.max(axis=0).mean()) / 2.0)
        return max(0.0, min(1.0, round(score, 4)))
    except Exception:
        # Ultimate fallback to jaccard
        return _jaccard(set(list_a), set(list_b))



def compute_column_matches(
    tables_cols: dict[str, list[str]],
    threshold: float = 0.70,
    run_id: str = "",
) -> SemanticMatchesReport:
    """BO1-06 Phase 4: Compute pairwise cross-table column similarity matches.

    Identifies shared business concepts and candidate foreign keys across tables.
    Returns a SemanticMatchesReport contract with typed relationships.
    """
    matches: list[SemanticMatch] = []
    table_names = sorted(tables_cols.keys())
    total_comparisons = 0

    for i in range(len(table_names)):
        t1 = table_names[i]
        cols1 = tables_cols[t1]
        for j in range(i + 1, len(table_names)):
            t2 = table_names[j]
            cols2 = tables_cols[t2]
            for c1 in cols1:
                norm1 = _normalize(c1)
                for c2 in cols2:
                    norm2 = _normalize(c2)
                    total_comparisons += 1

                    # 1. Exact match on normalized names
                    if norm1 == norm2:
                        is_key = c1.lower().endswith("_id") or c1.lower() == "id"
                        rel_type = RelationshipType.SAME_CONCEPT_CANDIDATE
                        score = 1.0
                        evidence_str = (
                            f"Identical column '{c1}' across tables {t1} and {t2} (candidate join key)"
                            if is_key else f"Identical column '{c1}' across tables {t1} and {t2}"
                        )
                        matches.append(SemanticMatch(
                            source_table=t1,
                            source_column=c1,
                            target_table=t2,
                            target_column=c2,
                            relationship_type=rel_type,
                            similarity_score=score,
                            evidence=[evidence_str],
                            review_required=False,
                        ))
                        continue

                    # 2. Similarity comparison (Embeddings / TF-IDF Hungarian on 1-to-1)
                    sim_res = compute_hungarian_similarity([c1], [c2])
                    score = sim_res.get("score", 0.0)

                    if score >= threshold:
                        rel_type = (
                            RelationshipType.SAME_CONCEPT_CANDIDATE
                            if score >= 0.88
                            else RelationshipType.RELATED_CONCEPT
                        )
                        review_req = score < 0.90
                        matches.append(SemanticMatch(
                            source_table=t1,
                            source_column=c1,
                            target_table=t2,
                            target_column=c2,
                            relationship_type=rel_type,
                            similarity_score=round(score, 4),
                            evidence=[f"Similarity score {score:.4f} via {sim_res.get('method')}"],
                            review_required=review_req,
                        ))

    return SemanticMatchesReport(
        schema_version="1.0.0",
        taxonomy_version="1.1.0",
        run_id=run_id,
        method="hungarian-cross-table@2.0",
        threshold=threshold,
        matches=matches,
        total_comparisons=total_comparisons,
        matches_found=len(matches),
    )


def run(ctx: RunContext) -> AgentResult:
    """Step 0: compute dataset similarity and pick the best playbook match."""
    upload = load(Upload, ctx.inputs["upload"])
    tables_dir: Path = ctx.inputs["tables"]

    # Collect all uploaded column names and table column mappings
    uploaded_cols: set[str] = set()
    tables_cols: dict[str, list[str]] = {}
    for table_name, csv_name in upload.tables.items():
        csv_path = tables_dir / csv_name
        if csv_path.exists():
            import csv as csv_mod
            with open(csv_path, encoding="utf-8", newline="") as fh:
                reader = csv_mod.reader(fh)
                header = next(reader, [])
                tables_cols[table_name] = header
                uploaded_cols.update(c.lower().strip() for c in header)

    # Score against known datasets using Hungarian + Jaccard
    matches: list[DatasetMatch] = []
    evidence_scores: dict[str, Any] = {}

    for ds_name, ref_cols in _KNOWN_DATASETS.items():
        jaccard_score = _jaccard(uploaded_cols, {c.lower().strip() for c in ref_cols})

        # Hungarian optimal alignment (BO1-06 Phase 2)
        hungarian_result = compute_hungarian_similarity(uploaded_cols, ref_cols)
        emb_score = hungarian_result["score"]
        assignment_detail = hungarian_result["assignment"]

        # Final score: max(jaccard, hungarian) — keep Jaccard as lower bound
        final_score = max(jaccard_score, emb_score)
        evidence_scores[ds_name] = {
            "jaccard": round(jaccard_score, 4),
            "hungarian_embedding": round(emb_score, 4),
            "hungarian_method": hungarian_result["method"],
            "hungarian_warning": hungarian_result.get("warning"),
            "top_assignments": assignment_detail[:5],   # only top-5 for audit log
            "final": round(final_score, 4),
        }
        if final_score >= THRESHOLD:
            matches.append(DatasetMatch(
                name=ds_name,
                score=round(final_score, 4),
                playbook=_PLAYBOOKS.get(ds_name),
            ))

    matches.sort(key=lambda m: m.score, reverse=True)
    best = matches[0] if matches else None

    # Determine accurate method name based on actual execution path
    actual_methods = {v.get("hungarian_method") for v in evidence_scores.values() if v.get("hungarian_method")}
    if "hungarian_embedding" in actual_methods:
        active_method = "hungarian-embedding@2.0"
    elif "hungarian_tfidf" in actual_methods:
        active_method = "hungarian-tfidf@2.0"
    else:
        active_method = "jaccard-fallback@1.0"
    method_name = f"{active_method}+jaccard"

    report = SimilarityReport(
        method=method_name,
        threshold=THRESHOLD,
        matches=matches,
        best_match=best,
    )

    out_path = ctx.output("report")
    save(report, out_path)

    # BO1-06 Phase 4: Compute and save cross-table column matches report
    col_matches_report = compute_column_matches(tables_cols, threshold=0.70, run_id=ctx.run_id)
    col_matches_path = ctx.output_dir / "column_matches.json"
    save(col_matches_report, col_matches_path)

    outputs_dict: dict[str, Path] = {
        "report": out_path,
        "column_matches": col_matches_path,
    }

    ctx.log(
        "dataset_similarity", "SUCCESS",
        inputs=[str(ctx.inputs["upload"])],
        outputs=[str(out_path), str(col_matches_path)],
        rule_version=f"similarity:{method_name}",
        evidence={
            "uploaded_columns": len(uploaded_cols),
            "matches": len(matches),
            "best_match": best.name if best else None,
            "best_score": best.score if best else None,
            "column_matches_found": col_matches_report.matches_found,
            "scores_detail": evidence_scores,
        },
    )

    msg = (f"Best match: {best.name} (score={best.score:.2f}, playbook={best.playbook}), "
           f"found {col_matches_report.matches_found} cross-table column match(es)."
           if best else f"No dataset matched. Found {col_matches_report.matches_found} cross-table column match(es).")

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs=outputs_dict,
        message=msg,
    )
