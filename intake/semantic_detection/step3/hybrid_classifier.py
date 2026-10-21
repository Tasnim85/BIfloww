"""intake/semantic_detection/step3/hybrid_classifier.py — Step 3 Hybrid Classifier.

Owner  : Malek  (BIFlow Semantic Detection — Step 3)
Purpose: Arbitrate between Step 2 rule-based classification and Step 3 embedding-based
         classification to produce a single, confident semantic type for each column.

Architecture
────────────
                ┌────────────────────────────────┐
                │    RuleBasedClassifier (Step 2) │
                │  →  ClassificationResult        │
                └────────────────┬───────────────┘
                                 │ (rule_type, rule_conf, match_tier)
                ┌────────────────▼───────────────┐
                │   HybridClassifier.classify()   │
                │                                 │
                │  Arbitration policy:            │
                │  ① alias tier (≥0.95)  → trust rule, skip embeddings
                │  ② keyword tier (≥0.75) → trust rule, skip embeddings
                │  ③ pattern / context   → compare rule vs embedding;
                │                          pick winner by score gap
                │  ④ unknown tier         → embeddings decisive;
                │                          fall back to UNKNOWN if sim < θ
                └────────────────┬───────────────┘
                                 │
                ┌────────────────▼───────────────┐
                │        HybridResult             │
                │  semantic_type, confidence,     │
                │  method, review_required, …     │
                └────────────────────────────────┘

Embedding support
─────────────────
sentence-transformers (all-MiniLM-L6-v2) is **optional**.
If not installed, the classifier gracefully falls back to TF-IDF cosine similarity
using sklearn.  If sklearn is also unavailable it falls back to Jaccard token overlap.
No internet connection is required after the first model download.

This module is a **pure classification function** and does NOT:
  • implement an orchestrator or DAG,
  • perform PII masking / hashing (Ikbel's domain),
  • compute statistical profiling (Ahmed's domain),
  • modify shared contracts (contracts/agent.py etc.),
  • require a GPU.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from intake.semantic_detection.step2.rule_classifier import (
    ClassificationResult,
    RuleBasedClassifier,
)
from intake.semantic_detection.step2.schema_reader import ColumnSchema, TableSchema

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_DEFAULT_DESCRIPTIONS_YAML = (
    Path(__file__).resolve().parent.parent / "config" / "semantic_descriptions.yaml"
)
_DEFAULT_RULES_YAML = (
    Path(__file__).resolve().parent.parent / "config" / "classification_rules.yaml"
)
_DEFAULT_TAXONOMY_YAML = (
    Path(__file__).resolve().parent.parent / "config" / "semantic_types.yaml"
)

# ── Thresholds ────────────────────────────────────────────────────────────────

# Rule-confidence thresholds above which we trust the rule directly.
_ALIAS_TRUST_THRESHOLD = 0.95      # alias tier — always trust rule
_KEYWORD_TRUST_THRESHOLD = 0.75    # keyword tier — trust rule
# Embedding similarity threshold to prefer embedding over rule.
_EMBEDDING_MIN_THRESHOLD = 0.60    # unknown-tier: min sim to accept embedding result
_EMBEDDING_OVERRIDE_THRESHOLD = 0.65  # pattern/context: min sim to override rule
# Gap beyond which conflict is flagged for human review.
_CONFLICT_GAP = 0.15


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class HybridResult:
    """Hybrid classification outcome for one column.

    Attributes:
        table: Source table name.
        column: Column name.
        semantic_type: Final decided semantic type_id.
        semantic_group: Taxonomy group_id of the final type.
        confidence: Final confidence score [0.0, 1.0].
        method: Decision method: "rule", "embedding", or "hybrid".
        rule_type: Semantic type proposed by Step 2 rule engine.
        rule_confidence: Confidence of the Step 2 rule.
        rule_tier: Match tier reported by Step 2 ("alias" | "keyword" | "pattern" |
                   "context" | "unknown").
        embedding_type: Best-matching semantic type from embedding similarity.
        embedding_score: Cosine or jaccard similarity score of the embedding match.
        embedding_backend: Backend used: "sentence-transformers", "tfidf", or "jaccard".
        review_required: True when rule and embedding disagree by more than _CONFLICT_GAP.
        privacy_hint: Privacy hint from taxonomy for the final type.
        evidence: Free-form dict for debugging / audit.
    """

    table: str
    column: str
    semantic_type: str
    semantic_group: str
    confidence: float
    method: str                          # "rule" | "embedding" | "hybrid"
    rule_type: str
    rule_confidence: float
    rule_tier: str
    embedding_type: Optional[str] = None
    embedding_score: float = 0.0
    embedding_backend: str = "none"
    review_required: bool = False
    privacy_hint: str = "NO_DIRECT_PII_INDICATOR"
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to plain dict for JSON/Pydantic downstream."""
        return {
            "table": self.table,
            "column": self.column,
            "semantic_type": self.semantic_type,
            "semantic_group": self.semantic_group,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "rule_type": self.rule_type,
            "rule_confidence": round(self.rule_confidence, 4),
            "rule_tier": self.rule_tier,
            "embedding_type": self.embedding_type,
            "embedding_score": round(self.embedding_score, 4),
            "embedding_backend": self.embedding_backend,
            "review_required": self.review_required,
            "privacy_hint": self.privacy_hint,
            "evidence": self.evidence,
        }


# ── Embedding backend (lazy, optional) ───────────────────────────────────────

def _try_sentence_transformers(descriptions: dict[str, str]) -> Optional[Any]:
    """Try to load sentence-transformers and pre-encode type descriptions.

    Returns a tuple (model, type_vectors, type_ids) or None if unavailable.
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # type: ignore

        model = SentenceTransformer("all-MiniLM-L6-v2")
        type_ids = list(descriptions.keys())
        texts = [descriptions[t] for t in type_ids]
        vectors = model.encode(texts, normalize_embeddings=True)
        logger.info("Step 3: sentence-transformers backend loaded (%d types).", len(type_ids))
        return ("sentence-transformers", model, vectors, type_ids, np)
    except Exception as exc:  # pragma: no cover
        logger.debug("sentence-transformers unavailable (%s). Trying TF-IDF.", exc)
        return None


def _try_tfidf(descriptions: dict[str, str]) -> Optional[Any]:
    """Fallback: TF-IDF vectoriser over type description strings."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
        from sklearn.metrics.pairwise import cosine_similarity  # type: ignore
        import numpy as np  # type: ignore

        type_ids = list(descriptions.keys())
        texts = [descriptions[t] for t in type_ids]
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        matrix = vec.fit_transform(texts)
        logger.info("Step 3: TF-IDF fallback backend loaded (%d types).", len(type_ids))
        return ("tfidf", vec, matrix, type_ids, cosine_similarity, np)
    except Exception as exc:  # pragma: no cover
        logger.debug("sklearn TF-IDF unavailable (%s). Using Jaccard fallback.", exc)
        return None


def _jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


# ── Hybrid Classifier ─────────────────────────────────────────────────────────

class HybridClassifier:
    """Arbitrate Step 2 rule output vs Step 3 embedding similarity.

    Args:
        descriptions_yaml: Path to ``semantic_descriptions.yaml``.
        rules_yaml: Path to ``classification_rules.yaml``.
        taxonomy_yaml: Path to ``semantic_types.yaml``.
        alias_threshold: Confidence above which alias-tier rules are trusted directly.
        keyword_threshold: Confidence above which keyword-tier rules are trusted directly.
        embedding_min_threshold: Min embedding similarity to accept embedding for UNKNOWN columns.
        embedding_override_threshold: Min embedding similarity to override a weak rule.
        conflict_gap: Score gap beyond which ``review_required`` is set to True.
    """

    def __init__(
        self,
        *,
        descriptions_yaml: Path | str = _DEFAULT_DESCRIPTIONS_YAML,
        rules_yaml: Path | str = _DEFAULT_RULES_YAML,
        taxonomy_yaml: Path | str = _DEFAULT_TAXONOMY_YAML,
        alias_threshold: float = _ALIAS_TRUST_THRESHOLD,
        keyword_threshold: float = _KEYWORD_TRUST_THRESHOLD,
        embedding_min_threshold: float = _EMBEDDING_MIN_THRESHOLD,
        embedding_override_threshold: float = _EMBEDDING_OVERRIDE_THRESHOLD,
        conflict_gap: float = _CONFLICT_GAP,
    ) -> None:
        self._alias_threshold = alias_threshold
        self._keyword_threshold = keyword_threshold
        self._embedding_min_threshold = embedding_min_threshold
        self._embedding_override_threshold = embedding_override_threshold
        self._conflict_gap = conflict_gap

        # Load descriptions
        self._descriptions: dict[str, str] = {}  # type_id → rich description string
        self._synonyms: dict[str, list[str]] = {}  # type_id → synonyms
        self._group_map: dict[str, str] = {}  # type_id → group_id
        self._privacy_map: dict[str, str] = {}  # type_id → privacy_hint
        self._load_descriptions(Path(descriptions_yaml))

        # Load taxonomy for group/privacy lookup
        self._load_taxonomy(Path(taxonomy_yaml))

        # Step 2 rule engine
        self._rule_classifier = RuleBasedClassifier(
            rules_yaml=rules_yaml,
            taxonomy_yaml=taxonomy_yaml,
        )

        # Init embedding backend (lazy)
        self._backend: Optional[tuple] = None
        self._backend_name: str = "jaccard"  # will be updated
        self._init_backend()

    # ── Initialisation helpers ─────────────────────────────────────────────

    def _load_descriptions(self, path: Path) -> None:
        """Load semantic_descriptions.yaml and build lookup maps."""
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for type_id, meta in data.get("types", {}).items():
            desc = meta.get("description_en", "")
            syns = meta.get("synonyms", [])
            # Build a rich composite text: description + synonyms + examples
            examples = meta.get("examples", [])
            corpus = desc + " " + " ".join(syns) + " " + " ".join(examples)
            self._descriptions[type_id] = corpus
            self._synonyms[type_id] = syns
            # Pre-fill group / privacy from descriptions file (will be overridden by taxonomy)
            self._group_map[type_id] = meta.get("semantic_group", "UNKNOWN_DATA")

    def _load_taxonomy(self, path: Path) -> None:
        """Load taxonomy YAML to fill group_map and privacy_map."""
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for group in data.get("groups", []):
            g_id = group["group_id"]
            for t in group.get("types", []):
                t_id = t["type_id"]
                self._group_map[t_id] = g_id
                self._privacy_map[t_id] = t.get("privacy_hint", "NO_DIRECT_PII_INDICATOR")

    def _init_backend(self) -> None:
        """Attempt to load the best available embedding backend."""
        result = _try_sentence_transformers(self._descriptions)
        if result is not None:
            self._backend = result
            self._backend_name = "sentence-transformers"
            return
        result = _try_tfidf(self._descriptions)
        if result is not None:
            self._backend = result
            self._backend_name = "tfidf"
            return
        # Pure Jaccard fallback — no backend object needed
        self._backend = None
        self._backend_name = "jaccard"
        logger.info("Step 3: Jaccard fallback backend active.")

    # ── Embedding similarity ───────────────────────────────────────────────

    def _embedding_best_match(self, query: str) -> tuple[str, float]:
        """Return (best_type_id, similarity_score) for a query string.

        The query is the column name (possibly normalised).  The match is against
        the pre-built description corpus of all taxonomy types.
        """
        if self._backend_name == "sentence-transformers":
            _, model, vectors, type_ids, np = self._backend  # type: ignore[misc]
            q_vec = model.encode([query], normalize_embeddings=True)
            sims = (vectors @ q_vec.T).flatten()
            best_idx = int(np.argmax(sims))
            return type_ids[best_idx], float(sims[best_idx])

        if self._backend_name == "tfidf":
            _, vec, matrix, type_ids, cosine_similarity, np = self._backend  # type: ignore[misc]
            try:
                q_vec = vec.transform([query])
                sims = cosine_similarity(q_vec, matrix).flatten()
                best_idx = int(np.argmax(sims))
                return type_ids[best_idx], float(sims[best_idx])
            except Exception:
                pass  # fall through to Jaccard

        # Jaccard fallback
        best_type = "UNKNOWN"
        best_score = 0.0
        for type_id, corpus in self._descriptions.items():
            score = _jaccard(query, corpus)
            if score > best_score:
                best_score = score
                best_type = type_id
        return best_type, best_score

    # ── Arbitration policy ─────────────────────────────────────────────────

    def _arbitrate(
        self,
        rule_result: ClassificationResult,
        col_query: str,
    ) -> HybridResult:
        """Apply arbitration policy and produce a HybridResult.

        Policy
        ------
        ① alias tier or rule_conf ≥ alias_threshold → trust rule, skip embeddings.
        ② keyword tier and rule_conf ≥ keyword_threshold → trust rule, skip embeddings.
        ③ pattern / context tier (rule_conf < keyword_threshold) →
              run embeddings; if emb_sim > override_threshold AND emb_type != rule_type
              and gap > conflict_gap → embedding wins with review_required flag.
              Otherwise keep rule.
        ④ unknown tier (conf = 0.0) →
              run embeddings; if emb_sim ≥ embedding_min_threshold → embedding wins.
              Else stay UNKNOWN.
        """
        tier = rule_result.match_tier
        r_type = rule_result.semantic_type
        r_conf = rule_result.confidence

        evidence: dict[str, Any] = {
            "rule_type": r_type,
            "rule_confidence": r_conf,
            "rule_tier": tier,
            "query": col_query,
        }

        # ─ Policy ①: alias tier — always trust rule ─────────────────────
        if tier == "alias" or r_conf >= self._alias_threshold:
            return HybridResult(
                table=rule_result.table,
                column=rule_result.column,
                semantic_type=r_type,
                semantic_group=self._group_map.get(r_type, "UNKNOWN_DATA"),
                confidence=r_conf,
                method="rule",
                rule_type=r_type,
                rule_confidence=r_conf,
                rule_tier=tier,
                embedding_type=None,
                embedding_score=0.0,
                embedding_backend="skipped",
                review_required=False,
                privacy_hint=self._privacy_map.get(r_type, "NO_DIRECT_PII_INDICATOR"),
                evidence={**evidence, "decision": "alias/high-conf rule trusted"},
            )

        # ─ Policy ②: keyword tier with sufficient confidence ────────────
        if tier == "keyword" and r_conf >= self._keyword_threshold:
            return HybridResult(
                table=rule_result.table,
                column=rule_result.column,
                semantic_type=r_type,
                semantic_group=self._group_map.get(r_type, "UNKNOWN_DATA"),
                confidence=r_conf,
                method="rule",
                rule_type=r_type,
                rule_confidence=r_conf,
                rule_tier=tier,
                embedding_type=None,
                embedding_score=0.0,
                embedding_backend="skipped",
                review_required=False,
                privacy_hint=self._privacy_map.get(r_type, "NO_DIRECT_PII_INDICATOR"),
                evidence={**evidence, "decision": "keyword rule trusted (conf≥threshold)"},
            )

        # All other tiers → run embeddings
        emb_type, emb_score = self._embedding_best_match(col_query)
        evidence["embedding_type"] = emb_type
        evidence["embedding_score"] = emb_score
        evidence["embedding_backend"] = self._backend_name

        # ─ Policy ④: unknown tier — embedding decisive ──────────────────
        if tier == "unknown" or r_conf == 0.0:
            if emb_score >= self._embedding_min_threshold:
                return HybridResult(
                    table=rule_result.table,
                    column=rule_result.column,
                    semantic_type=emb_type,
                    semantic_group=self._group_map.get(emb_type, "UNKNOWN_DATA"),
                    confidence=emb_score,
                    method="embedding",
                    rule_type=r_type,
                    rule_confidence=r_conf,
                    rule_tier=tier,
                    embedding_type=emb_type,
                    embedding_score=emb_score,
                    embedding_backend=self._backend_name,
                    review_required=False,
                    privacy_hint=self._privacy_map.get(emb_type, "NO_DIRECT_PII_INDICATOR"),
                    evidence={**evidence, "decision": "embedding decisive (unknown rule)"},
                )
            else:
                return HybridResult(
                    table=rule_result.table,
                    column=rule_result.column,
                    semantic_type="UNKNOWN",
                    semantic_group="UNKNOWN_DATA",
                    confidence=0.0,
                    method="hybrid",
                    rule_type=r_type,
                    rule_confidence=r_conf,
                    rule_tier=tier,
                    embedding_type=emb_type,
                    embedding_score=emb_score,
                    embedding_backend=self._backend_name,
                    review_required=True,
                    privacy_hint="NO_DIRECT_PII_INDICATOR",
                    evidence={**evidence, "decision": "both methods uncertain → UNKNOWN"},
                )

        # ─ Policy ③: pattern / context (or low-conf keyword) ────────────
        # Check if embedding strongly overrides rule.
        gap = abs(emb_score - r_conf)
        emb_overrides = (
            emb_score >= self._embedding_override_threshold
            and emb_type != r_type
            and gap >= self._conflict_gap
        )

        if emb_overrides:
            review_flag = True  # conflict detected → flag for human review
            final_type = emb_type if emb_score > r_conf else r_type
            final_conf = max(emb_score, r_conf)
            final_method = "hybrid"
        else:
            review_flag = False
            final_type = r_type
            final_conf = r_conf
            final_method = "rule"

        return HybridResult(
            table=rule_result.table,
            column=rule_result.column,
            semantic_type=final_type,
            semantic_group=self._group_map.get(final_type, "UNKNOWN_DATA"),
            confidence=final_conf,
            method=final_method,
            rule_type=r_type,
            rule_confidence=r_conf,
            rule_tier=tier,
            embedding_type=emb_type,
            embedding_score=emb_score,
            embedding_backend=self._backend_name,
            review_required=review_flag,
            privacy_hint=self._privacy_map.get(final_type, "NO_DIRECT_PII_INDICATOR"),
            evidence={
                **evidence,
                "gap": gap,
                "emb_overrides": emb_overrides,
                "decision": "embedding overrides weak rule" if emb_overrides else "rule kept over embedding",
            },
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def classify(
        self,
        col: ColumnSchema,
        table_context: Optional[TableSchema] = None,
    ) -> HybridResult:
        """Classify a single column through the hybrid pipeline.

        Args:
            col: Column descriptor (name, table, sample values).
            table_context: Optional full table schema for context matching.

        Returns:
            HybridResult with final semantic type and audit metadata.
        """
        # Step 2 — rule-based classification
        rule_result: ClassificationResult = self._rule_classifier.classify_column(
            col, table_context=table_context
        )

        # Build query string for embeddings (column name cleaned)
        col_query = col.column.replace("_", " ").lower()

        return self._arbitrate(rule_result, col_query)

    def classify_table(
        self,
        table: TableSchema,
    ) -> list[HybridResult]:
        """Classify all columns in a table.

        Args:
            table: Full table schema with all columns.

        Returns:
            List of HybridResult, one per column.
        """
        results: list[HybridResult] = []
        for col in table.columns:
            result = self.classify(col, table_context=table)
            results.append(result)
        return results

    def classify_schema(
        self,
        tables: list[TableSchema],
    ) -> dict[str, list[HybridResult]]:
        """Classify all tables in a multi-table schema.

        Args:
            tables: List of TableSchema objects.

        Returns:
            Dict mapping table_name → list of HybridResult.
        """
        return {table.table: self.classify_table(table) for table in tables}

    # ── Statistics helper ──────────────────────────────────────────────────

    @staticmethod
    def summary_stats(results: list[HybridResult]) -> dict:
        """Compute aggregate statistics over a list of HybridResult.

        Returns a dict with keys:
            total, by_method, avg_confidence, review_required_count,
            unknown_count, pii_hint_count.
        """
        total = len(results)
        if total == 0:
            return {"total": 0}

        by_method: dict[str, int] = {}
        review_count = 0
        unknown_count = 0
        pii_count = 0
        conf_sum = 0.0

        for r in results:
            by_method[r.method] = by_method.get(r.method, 0) + 1
            if r.review_required:
                review_count += 1
            if r.semantic_type == "UNKNOWN":
                unknown_count += 1
            if r.privacy_hint in ("LIKELY_PII", "POTENTIAL_PII"):
                pii_count += 1
            conf_sum += r.confidence

        return {
            "total": total,
            "by_method": by_method,
            "avg_confidence": round(conf_sum / total, 4),
            "review_required_count": review_count,
            "unknown_count": unknown_count,
            "pii_hint_count": pii_count,
        }
