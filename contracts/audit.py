"""Contract 4: one audit event format, written by every agent, read by the Auditor."""
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    run_id: str
    agent: str                        # who
    step: str                         # what, e.g. "join_multiplicity_check"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  # when
    inputs: list[str] = Field(default_factory=list)    # files or tables read
    outputs: list[str] = Field(default_factory=list)   # files or tables written
    decision: str                     # e.g. "FAILED", "filled with 'Unknown'"
    rule_version: str | None = None   # e.g. "kpi:revenue@2.0", "playbook:olist@1.3"
    evidence: dict = Field(default_factory=dict)       # facts that justify the decision


def log_event(event: AuditEvent, journal: Path = Path("runs/audit_journal.jsonl")) -> None:
    """Append-only: one JSON line per event, never rewritten."""
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as f:
        f.write(event.model_dump_json() + "\n")
