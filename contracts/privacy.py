"""Step 1b: PII detection and masking. Owner: Ikbel. Read by: Auditor, app.

The masked tables are written to runs/<run_id>/pii/tables/<table>.parquet.
From here on, NO agent reads the raw upload any more: everybody uses pii/tables.
"""
from enum import Enum

from contracts.common import Artifact, Contract


class PiiKind(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PERSON_NAME = "PERSON_NAME"
    ADDRESS = "ADDRESS"
    ZIP_CODE = "ZIP_CODE"
    PERSON_ID = "PERSON_ID"      # an identifier that points to one person
    OTHER = "OTHER"


class PiiAction(str, Enum):
    PSEUDONYMIZED = "pseudonymized"   # replaced by a stable hash: joins still work
    DROPPED = "dropped"               # column removed
    GENERALIZED = "generalized"       # e.g. full zip -> 3-digit prefix
    KEPT = "kept"                     # judged not personal after review


class PiiColumn(Contract):
    table: str
    column: str
    pii_kind: PiiKind
    action: PiiAction
    method: str                       # e.g. "sha256 + secret salt", "regex email"
    rows_affected: int


class PiiReport(Artifact):
    policy_version: str               # e.g. "pii-policy@1.0"
    columns: list[PiiColumn]
    tables: dict[str, str]            # table name -> parquet file name inside pii/tables/
    # The salt itself is NEVER written in any file or log.
