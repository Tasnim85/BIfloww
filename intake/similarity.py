"""intake/similarity.py — Step 0: dataset similarity detection (Malek — BO1-06).

Compares uploaded column names against known datasets (e.g. Olist sample)
using both embedding-based cosine similarity (BO1-06) and lexical Jaccard overlap.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import load, save
from contracts.intake import DatasetMatch, SimilarityReport, Upload

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


def compute_embedding_similarity(cols_a: list[str] | set[str], cols_b: list[str] | set[str]) -> float:
    """Compute semantic vector similarity between two column sets using embeddings.
    
    Uses SentenceTransformer cosine similarity when available, falling back to
    character n-gram TF-IDF cosine similarity.
    """
    list_a = [_normalize(c) for c in cols_a if c]
    list_b = [_normalize(c) for c in cols_b if c]
    if not list_a or not list_b:
        return 0.0
    
    # Identical sets check
    if set(list_a) == set(list_b):
        return 1.0

    model = _get_embedding_model()
    if model is not None:
        try:
            import numpy as np
            emb_a = model.encode(list_a, convert_to_numpy=True, normalize_embeddings=True)
            emb_b = model.encode(list_b, convert_to_numpy=True, normalize_embeddings=True)
            # Pairwise cosine similarities: shape (len(a), len(b))
            sim_matrix = np.dot(emb_a, emb_b.T)
            # Bidirectional best match average:
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


def run(ctx: RunContext) -> AgentResult:
    """Step 0: compute dataset similarity and pick the best playbook match."""
    upload = load(Upload, ctx.inputs["upload"])
    tables_dir: Path = ctx.inputs["tables"]

    # Collect all uploaded column names
    uploaded_cols: set[str] = set()
    for csv_name in upload.tables.values():
        csv_path = tables_dir / csv_name
        if csv_path.exists():
            import csv as csv_mod
            with open(csv_path, encoding="utf-8", newline="") as fh:
                reader = csv_mod.reader(fh)
                header = next(reader, [])
                uploaded_cols.update(c.lower().strip() for c in header)

    # Score against known datasets using both Jaccard and Embeddings
    matches: list[DatasetMatch] = []
    evidence_scores: dict[str, Any] = {}

    for ds_name, ref_cols in _KNOWN_DATASETS.items():
        jaccard_score = _jaccard(uploaded_cols, {c.lower().strip() for c in ref_cols})
        emb_score = compute_embedding_similarity(uploaded_cols, ref_cols)
        # Use embedding score as primary if available, combined with jaccard
        final_score = max(jaccard_score, emb_score)
        evidence_scores[ds_name] = {
            "jaccard": round(jaccard_score, 4),
            "embedding_cosine": round(emb_score, 4),
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

    method_name = "embedding-cosine+jaccard@1.1" if _get_embedding_model() else "char-tfidf+jaccard@1.1"

    report = SimilarityReport(
        method=method_name,
        threshold=THRESHOLD,
        matches=matches,
        best_match=best,
    )

    out_path = ctx.output("report")
    save(report, out_path)

    ctx.log(
        "dataset_similarity", "SUCCESS",
        inputs=[str(ctx.inputs["upload"])],
        outputs=[str(out_path)],
        rule_version=f"similarity:{method_name}",
        evidence={
            "uploaded_columns": len(uploaded_cols),
            "matches": len(matches),
            "best_match": best.name if best else None,
            "best_score": best.score if best else None,
            "scores_detail": evidence_scores,
        },
    )

    msg = (f"Best match: {best.name} (score={best.score:.2f}, playbook={best.playbook})"
           if best else "No known dataset matched — new dataset, LLM rules will be proposed.")

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"report": out_path},
        message=msg,
    )
