"""intake/semantic_detection/step2/name_normalizer.py ÔÇö Step 2 Name Normalizer.

Owner  : Samar / Malek  (Step 2)
Purpose: Normalise raw column names into a canonical token sequence suitable
         for rule matching, while preserving all business vocabulary.

Pipeline (applied in order):
  1. Lowercase + strip whitespace.
  2. Expand known abbreviations (e.g. "qty" ÔåÆ "quantity", "amt" ÔåÆ "amount").
  3. Split on common delimiters (_, -, ┬À, space).
  4. Split camelCase / PascalCase boundaries.
  5. Remove purely numeric tokens (they carry no semantic signal).
  6. Preserve whitelisted business terms verbatim (e.g. "vat", "sku", "roi").

Public API::

    normalizer = NameNormalizer()
    result = normalizer.normalize("ProductQty_USD")
    # NormResult(
    #   original="ProductQty_USD",
    #   normalized_key="product_quantity_usd",
    #   tokens=["product", "quantity", "usd"],
    #   expanded_abbreviations={"qty": "quantity"},
    # )
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ÔöÇÔöÇ Default abbreviation table ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
# These expansions are applied *before* tokenisation so that compound forms
# like "cust_id" still produce a single recognised token for the ID rule.

_DEFAULT_ABBREVIATIONS: dict[str, str] = {
    # Identifiers
    "id":   "id",          # keep as-is ÔÇö handled by ID rule later
    "uid":  "uid",
    "uuid": "uuid",
    "ref":  "reference",
    # Quantities & money
    "qty":  "quantity",
    "amt":  "amount",
    "amt":  "amount",
    "pct":  "percentage",
    "pct":  "percentage",
    "num":  "number",
    "nb":   "number",
    "cnt":  "count",
    "avg":  "average",
    "max":  "maximum",
    "min":  "minimum",
    "tot":  "total",
    "rev":  "revenue",
    "cst":  "cost",
    "val":  "value",
    "cur":  "currency",
    "usd":  "usd",         # preserve as business term
    "eur":  "eur",
    "gbp":  "gbp",
    # Dates & time
    "dt":   "date",
    "ts":   "timestamp",
    "yr":   "year",
    "mo":   "month",
    "dy":   "day",
    "hr":   "hour",
    "min":  "minute",
    "sec":  "second",
    "dur":  "duration",
    # Geography
    "lat":  "latitude",
    "lng":  "longitude",
    "lon":  "longitude",
    "zip":  "postal_code",
    "addr": "address",
    "cty":  "city",
    "cntry": "country",
    # People
    "fn":   "first_name",
    "ln":   "last_name",
    "dob":  "birth_date",
    "tel":  "phone",
    "mob":  "mobile",
    # Technical
    "ver":  "version",
    "cfg":  "config",
    "env":  "environment",
    "url":  "url",
    # Business
    "sku":  "sku",          # preserved
    "roi":  "roi",          # preserved
    "kpi":  "kpi",          # preserved
    "vat":  "vat",          # preserved
    "cac":  "cac",          # preserved
    "ltv":  "ltv",          # preserved
    "mrr":  "mrr",          # preserved
    "arr":  "arr",          # preserved
    "ebit": "ebit",         # preserved
    "cogs": "cogs",         # preserved
    "b2b":  "b2b",          # preserved
    "b2c":  "b2c",          # preserved
    # Products
    "prod": "product",
    "cat":  "category",
    "desc": "description",
    "img":  "image",
    "src":  "source",
    "dest": "destination",
    "orig": "origin",
}

# Terms that must be preserved exactly (not split or further expanded)
_BUSINESS_TERMS: frozenset[str] = frozenset({
    "sku", "roi", "kpi", "vat", "cac", "ltv", "mrr", "arr", "ebit",
    "cogs", "b2b", "b2c", "usd", "eur", "gbp", "url", "uuid", "uid",
    "pii", "gdpr", "ccpa", "sla", "api", "sdk", "crm", "erp", "bi",
})

# ÔöÇÔöÇ Data model ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

@dataclass
class NormResult:
    """Result of normalising one column name."""
    original: str
    normalized_key: str            # lowercase, underscores, expansions applied
    tokens: list[str]              # individual meaningful tokens
    expanded_abbreviations: dict[str, str] = field(default_factory=dict)
    preserved_business_terms: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"NormResult(original={self.original!r}, "
            f"key={self.normalized_key!r}, tokens={self.tokens})"
        )


# ÔöÇÔöÇ Normalizer ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

class NameNormalizer:
    """Column name normaliser for BIFlow Step 2.

    Args:
        abbreviations: Custom abbreviation map (merged over defaults).
        business_terms: Additional terms to preserve verbatim.
        extra_yaml: Path to a YAML file with ``abbreviations:`` and/or
                    ``business_terms:`` keys (optional).
    """

    def __init__(
        self,
        *,
        abbreviations: dict[str, str] | None = None,
        business_terms: set[str] | None = None,
        extra_yaml: Path | str | None = None,
    ) -> None:
        self._abbrev: dict[str, str] = dict(_DEFAULT_ABBREVIATIONS)
        self._terms: set[str] = set(_BUSINESS_TERMS)

        if extra_yaml:
            self._load_yaml(Path(extra_yaml))

        if abbreviations:
            self._abbrev.update({k.lower(): v.lower() for k, v in abbreviations.items()})
        if business_terms:
            self._terms.update(t.lower() for t in business_terms)

    # ÔöÇÔöÇ Public API ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

    def normalize(self, column_name: str) -> NormResult:
        """Normalise one column name.

        Args:
            column_name: Raw column name as it appears in the schema.

        Returns:
            A :class:`NormResult` with tokens, normalized key, and expansion details.
        """
        original = column_name
        expanded: dict[str, str] = {}
        preserved: list[str] = []

        # Step 1 ÔÇö split camelCase on the ORIGINAL string (before lowercasing)
        # so that "ProductQty" ÔåÆ "product_qty" boundaries are detected
        s = _split_camel(column_name.strip())

        # s is now already lowercase (returned by _split_camel)

        # Step 3 ÔÇö split on delimiters
        raw_tokens = [t for t in re.split(r"[_\-\.\s]+", s) if t]

        # Step 4 ÔÇö expand abbreviations token-by-token
        final_tokens: list[str] = []
        for tok in raw_tokens:
            if tok in self._terms:
                # Preserved business term ÔÇö keep as-is
                final_tokens.append(tok)
                preserved.append(tok)
            elif tok in self._abbrev and self._abbrev[tok] != tok:
                expansion = self._abbrev[tok]
                expanded[tok] = expansion
                # Expansion may itself be compound (e.g. "postal_code")
                final_tokens.extend(expansion.split("_"))
            else:
                final_tokens.append(tok)

        # Step 5 ÔÇö remove purely numeric tokens (no semantic signal)
        final_tokens = [t for t in final_tokens if not t.isdigit()]

        normalized_key = "_".join(final_tokens) if final_tokens else s.replace(" ", "_") or "unknown"

        return NormResult(
            original=original,
            normalized_key=normalized_key,
            tokens=final_tokens,
            expanded_abbreviations=expanded,
            preserved_business_terms=preserved,
        )

    def normalize_many(self, column_names: list[str]) -> list[NormResult]:
        """Normalise a list of column names."""
        return [self.normalize(c) for c in column_names]

    # ÔöÇÔöÇ Private helpers ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

    def _load_yaml(self, path: Path) -> None:
        with open(path, encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
        if "abbreviations" in data:
            self._abbrev.update({k.lower(): v.lower() for k, v in data["abbreviations"].items()})
        if "business_terms" in data:
            self._terms.update(t.lower() for t in data["business_terms"])


# ÔöÇÔöÇ Helpers ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

def _split_camel(s: str) -> str:
    """Insert underscores at camelCase / PascalCase boundaries.

    Examples::
        "ProductQty"   ÔåÆ "product_qty"
        "orderID"      ÔåÆ "order_id"
        "XMLParser"    ÔåÆ "xml_parser"
    """
    # Between lower/digit and Upper
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    # Between consecutive Uppers followed by lower (e.g. "XMLParser" ÔåÆ "XML_Parser")
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()

