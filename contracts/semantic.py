"""Business meaning: KPI catalog + glossary (Rabeb) and the request (Malek).

KpiCatalog       kpi/catalog.yaml        Rabeb -> Malek, Analyst, comparisons, lineage
Glossary         semantic/glossary.yaml  Rabeb -> Malek (embedding search)
AnalysisRequest  request step (BO4-06)   Malek -> Rabeb, Tasnim, Samar
"""
from pathlib import Path

import yaml
from pydantic import Field

from contracts.common import Artifact, Contract, Period


# ---- KPI catalog (YAML file in the repo, versioned) ----------------------------
class Dimension(Contract):
    name: str                          # what requests use, e.g. "customer_state"
    table: str                         # e.g. "dim_customer"
    column: str                        # e.g. "customer_state"
    description: str


class KpiDefinition(Contract):
    name: str                          # e.g. "Revenue"
    version: str                       # e.g. "2.0": bump it when the formula changes
    description: str
    expression: str                    # SQL aggregate, e.g. "SUM(payment_value)"
    table: str                         # fact table it is computed on
    grain: str                         # grain of that table, must match the manifest
    date_column: str                   # column used for periods
    unit: str                          # e.g. "BRL", "orders", "%"
    filters: list[str] = Field(default_factory=list)       # SQL WHERE parts
    allowed_dimensions: list[str] = Field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"   # used as rule_version "kpi:Revenue@2.0"


class KpiCatalog(Contract):
    version: str
    kpis: list[KpiDefinition]
    dimensions: list[Dimension]

    def kpi(self, name: str) -> KpiDefinition:
        return next(k for k in self.kpis if k.name == name)


# ---- Glossary (YAML file in the repo) --------------------------------------------
class GlossaryTerm(Contract):
    term: str                          # canonical name: a KPI or a dimension name
    kind: str                          # "metric" | "dimension" | "time"
    synonyms: list[str]                # e.g. ["sales", "chiffre d'affaires", "turnover"]
    definition: str


class Glossary(Contract):
    version: str
    terms: list[GlossaryTerm]


def load_yaml(cls, path: Path):
    """Load and validate a YAML file (catalog, glossary, playbook)."""
    return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


# ---- The request ------------------------------------------------------------------
class AnalysisRequest(Artifact):
    """Sarra's question turned into something a program can compute."""
    question: str                      # her words, unchanged
    metric: str                        # KPI name from the catalog, e.g. "Revenue"
    dimensions: list[str] = Field(default_factory=list)    # catalog dimension names
    period: Period
    compare_to: Period | None = None   # filled only if she asked for a comparison
    filters: list[str] = Field(default_factory=list)       # SQL WHERE parts
    confidence: float = 1.0            # how sure the matching is, [0, 1]
    matched_terms: dict[str, str] = Field(default_factory=dict)
    # words of the question -> glossary term, e.g. {"sales": "Revenue", "region": "customer_state"}
