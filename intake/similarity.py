"""intake/similarity.py — Step 0: dataset similarity detection (Malek — BO1-06 Phase 1).

Compares the uploaded column names against known datasets (Olist sample)
using simple Jaccard similarity on normalized column name sets.

Step 1 (this file): column-name Jaccard similarity.
Step 2 (future):    sentence-embedding cosine similarity.
"""
from __future__ import annotations

from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import load, save
from contracts.intake import DatasetMatch, SimilarityReport, Upload

# Known dataset fingerprints (column name sets).
# Extended in Step 2 via embedding index over the data/sample/ folder.
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

THRESHOLD = 0.4   # Jaccard ≥ 0.4 → match


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _normalize(name: str) -> str:
    return name.lower().strip()


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
                uploaded_cols.update(_normalize(c) for c in header)

    # Score against known datasets
    matches: list[DatasetMatch] = []
    for ds_name, ref_cols in _KNOWN_DATASETS.items():
        score = _jaccard(uploaded_cols, {_normalize(c) for c in ref_cols})
        if score >= THRESHOLD:
            matches.append(DatasetMatch(
                name=ds_name,
                score=round(score, 4),
                playbook=_PLAYBOOKS.get(ds_name),
            ))

    matches.sort(key=lambda m: m.score, reverse=True)
    best = matches[0] if matches else None

    report = SimilarityReport(
        method="column-name-jaccard@1.0",
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
        rule_version="similarity:jaccard@1.0",
        evidence={
            "uploaded_columns": len(uploaded_cols),
            "matches": len(matches),
            "best_match": best.name if best else None,
            "best_score": best.score if best else None,
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
