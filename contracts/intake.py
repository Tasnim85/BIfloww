"""Files written at the start of a run.

Upload            written by the app (Samar),            read by Malek, Ikbel
SimilarityReport  written by similarity, step 0 (Malek), read by cleaning (Ikbel)
ColumnTypesReport written by step 1a (Malek),            read by PII (Ikbel), profiling (Ahmed)
"""
from datetime import datetime, timezone

from pydantic import Field

from contracts.common import Artifact, Contract, SemanticType


class Upload(Artifact):
    """What Sarra gave us. The CSV files are copied into runs/<run_id>/upload/tables/."""
    question: str                     # her words, e.g. "Revenue by state in August vs July"
    tables: dict[str, str]            # table name -> file name inside upload/tables/
    uploaded_by: str = "anonymous"
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DatasetMatch(Contract):
    name: str                          # a known dataset, e.g. "olist"
    score: float                       # similarity in [0, 1]
    playbook: str | None = None        # cleaning playbook to reuse, e.g. "olist@1.3"


class SimilarityReport(Artifact):
    """Step 0: does this upload look like a dataset we already know?"""
    method: str                        # e.g. "column-name embeddings + cosine"
    threshold: float                   # minimum score to accept a match
    matches: list[DatasetMatch]        # best first
    best_match: DatasetMatch | None    # None = new kind of dataset (cleaning uses the LLM, 2b)


class ColumnType(Contract):
    table: str
    column: str
    semantic_type: SemanticType
    confidence: float                  # [0, 1]
    pii_candidate: bool = False        # may hold personal data -> PII step looks at it


class ColumnTypesReport(Artifact):
    """Step 1a: the business type of every column of every uploaded table."""
    model: str                         # e.g. "rules+logreg@1.0"
    columns: list[ColumnType]
