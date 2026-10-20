"""Shared building blocks used by every other contract file.

Nothing here belongs to one person: change it only with the whole team.
"""
from enum import Enum
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

CONTRACTS_VERSION = "1.6"   # 1.6: *_parts fields (texts in any language, contracts/i18n.py)


class Contract(BaseModel):
    """Base for every contract object.

    extra="forbid": a misspelled or unknown field raises an error immediately,
    instead of silently disappearing between two agents.
    """
    model_config = ConfigDict(extra="forbid")


class Artifact(Contract):
    """Base for every FILE an agent writes (one JSON file = one Artifact).

    contract_version lets a reader detect a file written with an older contract.
    """
    contract_version: str = CONTRACTS_VERSION


class AgentName(str, Enum):
    """The steps of the pipeline. Also the folder names in runs/<run_id>/."""
    UPLOAD = "upload"              # written by the app (Samar), not an agent
    SIMILARITY = "similarity"      # 0   Malek
    COLUMN_TYPES = "column_types"  # 1a  Malek
    PII = "pii"                    # 1b  Ikbel
    PROFILING = "profiling"        # 2   Ahmed
    CLEANING = "cleaning"          # 2a/2b Ikbel
    ETL = "etl"                    # 3   Ahmed
    REQUEST = "request"            # 4   Malek (BO4-06)
    ANALYSIS = "analysis"          # 5   Rabeb
    COMPARISONS = "comparisons"    # 6   Tasnim (BO4-12)
    DASHBOARD = "dashboard"        # 6   Samar
    LINEAGE = "lineage"            #     Ahmed
    AUDITOR = "auditor"            # 7   Tasnim


class SemanticType(str, Enum):
    """Business type of a column (step 1a). Read by PII, profiling and cleaning."""
    ID = "ID"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PERSON_NAME = "PERSON_NAME"
    AGE = "AGE"
    AMOUNT = "AMOUNT"          # money
    QUANTITY = "QUANTITY"      # counts, units
    NUMBER = "NUMBER"          # other numeric measure (weight, length...)
    DATE = "DATE"
    DATETIME = "DATETIME"
    CITY = "CITY"
    STATE = "STATE"
    ZIP_CODE = "ZIP_CODE"
    CATEGORY = "CATEGORY"
    TEXT = "TEXT"              # free text (reviews, comments)
    BOOLEAN = "BOOLEAN"
    OTHER = "OTHER"


class Period(Contract):
    """A closed date interval, both ends INCLUDED. ISO dates: 'YYYY-MM-DD'."""
    start: str
    end: str


# ---- Reading and writing contract files ---------------------------------------
A = TypeVar("A", bound=BaseModel)


def save(obj: BaseModel, path: Path) -> Path:
    """Write a contract object as pretty JSON. Creates the folder if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    return path


def load(cls: type[A], path: Path) -> A:
    """Read a JSON file and VALIDATE it against its contract (raises if wrong)."""
    return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
