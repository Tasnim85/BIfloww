"""intake/semantic_detection/step2/rule_classifier.py ÔÇö Step 2 Rule-Based Classifier.



Owner  : Samar / Malek  (Step 2)

Purpose: Load YAML classification rules and classify each column schema into a

         (semantic_group, semantic_type, confidence) triple, aligned with the

         Step 1 taxonomy.



Classification pipeline (applied in priority order):

  1. Exact alias match from taxonomy YAML (confidence 0.95).

  2. Rule-file keyword match on normalized tokens (confidence from rule).

  3. Regex pattern match on sample values or column name (confidence from rule).

  4. Contextual match: neighbouring columns or table-name hints (confidence 0.60).

  5. Fallback: UNKNOWN_DATA / UNKNOWN (confidence 0.00).



Each classification step can be extended by adding rules to

``config/classification_rules.yaml``.

"""

from __future__ import annotations



import re

from dataclasses import dataclass, field

from pathlib import Path

from typing import Any



import yaml



from intake.semantic_detection.src.taxonomy_loader import TaxonomyLoader

from intake.semantic_detection.step2.schema_reader import ColumnSchema, TableSchema

from intake.semantic_detection.step2.name_normalizer import NameNormalizer, NormResult





# ÔöÇÔöÇ Classification result ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ



@dataclass

class ClassificationResult:

    """Classification outcome for one column."""

    table: str

    column: str

    normalized_key: str

    tokens: list[str]

    semantic_group: str       # taxonomy group_id

    semantic_type: str        # taxonomy type_id

    confidence: float         # [0.0, 1.0]

    match_tier: str           # "alias" | "keyword" | "pattern" | "context" | "unknown"

    privacy_hint: str         # from taxonomy

    matched_rule: str | None = None   # which rule triggered

    notes: list[str] = field(default_factory=list)



    @property

    def is_unknown(self) -> bool:

        return self.semantic_type == "UNKNOWN"



    @property

    def is_low_confidence(self) -> bool:

        return self.confidence < 0.50





# ÔöÇÔöÇ Rule-file structure ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

# Each entry in ``classification_rules.yaml`` looks like:

#

#   - rule_id: PRICE_RULE

#     priority: 10

#     group_id: FINANCIAL_DATA

#     type_id:  PRICE

#     match:

#       keywords:  [price, prix, tarif, msrp, srp]

#       table_hints: [product, catalogue]   # optional ÔÇö match only in certain tables

#       value_patterns:                      # optional regex applied to sample values

#         - "^\\d+\\.\\d{2}$"

#     confidence: 0.85

#     notes: "Matches monetary price columns"



@dataclass

class ClassificationRule:

    rule_id: str

    priority: int         # lower = higher priority

    group_id: str

    type_id: str

    keywords: list[str]

    table_hints: list[str]

    value_patterns: list[str]

    confidence: float

    notes: str = ""



    # Pre-compiled regexes (populated at load time)

    _compiled_patterns: list[re.Pattern] = field(default_factory=list, repr=False, compare=False)



    def compile(self) -> None:

        self._compiled_patterns = [

            re.compile(p, re.IGNORECASE) for p in self.value_patterns

        ]





# ÔöÇÔöÇ Classifier ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ



_DEFAULT_RULES_YAML = (

    Path(__file__).resolve().parent.parent / "config" / "classification_rules.yaml"

)



_DEFAULT_TAXONOMY_YAML = (

    Path(__file__).resolve().parent.parent / "config" / "semantic_types.yaml"

)





class RuleBasedClassifier:

    """Classify :class:`ColumnSchema` objects using the BIFlow taxonomy + YAML rules.



    Args:

        rules_yaml: Path to ``classification_rules.yaml``.

        taxonomy_yaml: Path to ``semantic_types.yaml`` (Step 1 taxonomy).

        normalizer: A :class:`NameNormalizer` instance (created if not provided).

    """



    def __init__(

        self,

        *,

        rules_yaml: Path | str = _DEFAULT_RULES_YAML,

        taxonomy_yaml: Path | str = _DEFAULT_TAXONOMY_YAML,

        normalizer: NameNormalizer | None = None,

    ) -> None:

        self._loader = TaxonomyLoader(taxonomy_yaml)

        self._normalizer = normalizer or NameNormalizer()

        self._rules: list[ClassificationRule] = []

        self._load_rules(Path(rules_yaml))



    # ÔöÇÔöÇ Public API ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ



    def classify_column(

        self,

        col: ColumnSchema,

        *,

        table_context: TableSchema | None = None,

    ) -> ClassificationResult:

        """Classify one :class:`ColumnSchema`.



        Args:

            col: The column to classify.

            table_context: Optional full table schema for contextual matching.



        Returns:

            A :class:`ClassificationResult`.

        """

        norm = self._normalizer.normalize(col.column)

        col_lower = col.column.lower().strip()



        # Tier 1 ÔÇö Exact alias from taxonomy YAML ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

        type_id = self._loader.type_id_from_alias(col_lower)

        if type_id:

            return self._make_result(col, norm, type_id, 0.95, "alias", f"taxonomy_alias:{col_lower}")



        # Tier 2 ÔÇö YAML rule keyword match ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

        table_name = (col.table or "").lower()

        result = self._match_rules_keyword(col, norm, table_name)

        if result:

            return result



        # Tier 3 ÔÇö YAML rule pattern match on sample values ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

        result = self._match_rules_pattern(col, norm, table_name)

        if result:

            return result



        # Tier 4 ÔÇö Contextual match (table name hints) ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

        result = self._match_contextual(col, norm, table_context)

        if result:

            return result



        # Tier 5 ÔÇö UNKNOWN fallback ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

        return ClassificationResult(

            table=col.table,

            column=col.column,

            normalized_key=norm.normalized_key,

            tokens=norm.tokens,

            semantic_group="UNKNOWN_DATA",

            semantic_type="UNKNOWN",

            confidence=0.00,

            match_tier="unknown",

            privacy_hint="NO_DIRECT_PII_INDICATOR",

            matched_rule=None,

            notes=["No taxonomy alias, keyword, pattern, or contextual match found."],

        )



    def classify_table(self, table: TableSchema) -> list[ClassificationResult]:

        """Classify all columns of a :class:`TableSchema`."""

        return [self.classify_column(col, table_context=table) for col in table.columns]



    def classify_tables(self, tables: list[TableSchema]) -> list[ClassificationResult]:

        """Classify all columns across multiple tables."""

        results: list[ClassificationResult] = []

        for table in tables:

            results.extend(self.classify_table(table))

        return results



    # ÔöÇÔöÇ Private: rule loading ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ



    def _load_rules(self, path: Path) -> None:

        if not path.exists():

            # Gracefully handle missing rule file ÔÇö taxonomy aliases still work

            return

        with open(path, encoding="utf-8") as fh:

            raw: Any = yaml.safe_load(fh) or {}



        rule_list = raw if isinstance(raw, list) else raw.get("rules", [])

        for rd in rule_list:

            rule = ClassificationRule(

                rule_id=rd.get("rule_id", "UNNAMED"),

                priority=int(rd.get("priority", 99)),

                group_id=rd.get("group_id", "UNKNOWN_DATA"),

                type_id=rd.get("type_id", "UNKNOWN"),

                keywords=[k.lower() for k in rd.get("match", {}).get("keywords", [])],

                table_hints=[h.lower() for h in rd.get("match", {}).get("table_hints", [])],

                value_patterns=rd.get("match", {}).get("value_patterns", []),

                confidence=float(rd.get("confidence", 0.70)),

                notes=rd.get("notes", ""),

            )

            rule.compile()

            self._rules.append(rule)



        # Sort by priority ascending (lower number = higher priority)

        self._rules.sort(key=lambda r: r.priority)



    # ÔöÇÔöÇ Private: matching tiers ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ



    def _match_rules_keyword(
        self, col: ColumnSchema, norm: NormResult, table_name: str
    ) -> ClassificationResult | None:
        col_lower = col.column.lower().strip()
        raw_tokens = set(re.split(r"[^a-zA-Z0-9]+", col_lower))
        all_tokens = set(norm.tokens) | raw_tokens

        for rule in self._rules:
            # Table-hint guard (if specified, must match)
            if rule.table_hints and not any(h in table_name for h in rule.table_hints):
                continue

            matched_kw = None
            for kw in rule.keywords:
                kw_clean = kw.strip().lower()
                if not kw_clean:
                    continue
                # 1. Exact match with full column or normalized key
                if kw_clean == col_lower or kw_clean == norm.normalized_key:
                    matched_kw = kw
                    break
                # 2. Explicit suffix (e.g. "_id", "_uid", "_key")
                if kw_clean.startswith("_"):
                    if col_lower.endswith(kw_clean) or norm.normalized_key.endswith(kw_clean):
                        matched_kw = kw
                        break
                    continue
                # 3. Explicit prefix (e.g. "is_", "has_")
                if kw_clean.endswith("_"):
                    if col_lower.startswith(kw_clean) or norm.normalized_key.startswith(kw_clean):
                        matched_kw = kw
                        break
                    continue
                # 4. Single token match: must be exact whole token (anchoring avoids "candidate" matching "date")
                if "_" not in kw_clean and "-" not in kw_clean:
                    if kw_clean in all_tokens:
                        matched_kw = kw
                        break
                    continue
                # 5. Multi-token keyword: bounded token sequence
                clean_col = col_lower.replace("-", "_")
                clean_kw = kw_clean.replace("-", "_")
                clean_norm = norm.normalized_key.replace("-", "_")
                padded_kw = f"_{clean_kw}_"
                if padded_kw in f"_{clean_col}_" or padded_kw in f"_{clean_norm}_":
                    matched_kw = kw
                    break

            if matched_kw is None:
                continue

            if not self._loader.is_valid_type(rule.type_id):
                continue

            return self._make_result(
                col, norm, rule.type_id, rule.confidence, "keyword",
                f"rule:{rule.rule_id}(kw={matched_kw!r})",
            )

        return None



    def _match_rules_pattern(

        self, col: ColumnSchema, norm: NormResult, table_name: str

    ) -> ClassificationResult | None:

        for rule in self._rules:

            if not rule._compiled_patterns:

                continue

            if rule.table_hints and not any(h in table_name for h in rule.table_hints):

                continue

            # Test patterns against each sample value

            for pat in rule._compiled_patterns:

                for val in col.sample_values:

                    if val and pat.search(str(val)):

                        if not self._loader.is_valid_type(rule.type_id):

                            continue

                        return self._make_result(

                            col, norm, rule.type_id,

                            min(rule.confidence, 0.80),   # cap pattern-only confidence

                            "pattern",

                            f"rule:{rule.rule_id}(pattern={pat.pattern!r})",

                        )

        return None



    def _match_contextual(

        self,

        col: ColumnSchema,

        norm: NormResult,

        table_context: TableSchema | None,

    ) -> ClassificationResult | None:

        """Use table name and sibling column names as additional signals."""

        if table_context is None:

            return None



        table_lower = table_context.table.lower()

        sibling_names = {c.column.lower() for c in table_context.columns if c.column != col.column}



        # Context heuristics: if the table name strongly hints a domain,

        # and the current column has only weak tokens, apply a domain boost.

        context_hints: list[tuple[str, str, str, float]] = [

            # (table_keyword, col_token, type_id, confidence)

            ("geolocation", "lat",  "LATITUDE",  0.60),

            ("geolocation", "lng",  "LONGITUDE", 0.60),

            ("geolocation", "zip",  "POSTAL_CODE", 0.60),

            ("order",       "status", "STATUS",  0.60),

            ("product",     "name",   "TITLE",   0.60),

            ("customer",    "name",   "PERSON_NAME", 0.55),

            ("review",      "score",  "RATING",  0.60),

            ("review",      "message", "COMMENT", 0.60),

            ("payment",     "value",  "PAYMENT_AMOUNT", 0.60),

            ("payment",     "type",   "PAYMENT_METHOD", 0.60),

        ]



        token_set = set(norm.tokens)

        for table_kw, col_tok, type_id, conf in context_hints:

            if table_kw in table_lower and col_tok in token_set:

                if self._loader.is_valid_type(type_id):

                    return self._make_result(

                        col, norm, type_id, conf, "context",

                        f"context:table={table_kw!r},token={col_tok!r}",

                    )

        return None



    def _make_result(

        self,

        col: ColumnSchema,

        norm: NormResult,

        type_id: str,

        confidence: float,

        tier: str,

        matched_rule: str | None,

    ) -> ClassificationResult:

        group_id = self._loader.group_for_type(type_id) or "UNKNOWN_DATA"

        privacy  = self._loader.privacy_hint_for(type_id) or "NO_DIRECT_PII_INDICATOR"

        return ClassificationResult(

            table=col.table,

            column=col.column,

            normalized_key=norm.normalized_key,

            tokens=norm.tokens,

            semantic_group=group_id,

            semantic_type=type_id,

            confidence=confidence,

            match_tier=tier,

            privacy_hint=privacy,

            matched_rule=matched_rule,

        )

