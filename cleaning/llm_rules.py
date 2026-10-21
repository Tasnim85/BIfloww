"""Local Pydantic rule format pending the shared contracts/quality.py.

The LLM sees column metadata only. A proposal never authorizes its own execution.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from bo2.local_llm import request_json
from cleaning.identifiers import is_financial, is_identifier, is_temporal


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    column: str
    action: Literal["trim", "numeric", "datetime", "fill_constant"]
    value: str | float | int | None = None

    @model_validator(mode="after")
    def conservative_policy(self):
        identifier = is_identifier(self.column)
        temporal = is_temporal(self.column)
        financial = is_financial(self.column)
        if self.action == "fill_constant" and (self.value is None or identifier or temporal or financial):
            raise ValueError("Never fabricate financial amounts, dates or identifiers; constant filling is restricted to noncritical categorical fields")
        if identifier and self.action in {"numeric", "datetime"}:
            raise ValueError("Never cast identifiers to numeric or datetime")
        if temporal and self.action not in {"trim", "datetime"}:
            raise ValueError("Temporal columns only support trim or datetime conversion")
        if financial and self.action not in {"trim", "numeric"}:
            raise ValueError("Financial columns only support trim or numeric conversion")
        return self


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(pattern=r"^\d+\.\d+$")
    rules: list[Rule] = Field(min_length=0, max_length=8)


def digest(proposal: Proposal) -> str:
    return hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()


def generate(metadata: dict, model: str, output: Path) -> Path:
    """Ask local Llama 3 for metadata-only proposals; human approval is still required."""
    allowed = {table: list(values.get("columns", {})) for table, values in metadata.get("tables", {}).items()}
    prompt = ("You design a conservative cleaning playbook. Return an object with name, version and rules. "
              "Each rule has table, column and action. Copy the EXACT table and column spelling from the supplied catalog. "
              "A column belongs ONLY to its containing table. Do not invent tables, columns, or operations. "
              "Suggest at most five useful rules; return an empty rules list if none are appropriate. Protected columns and keys have been excluded: do not reintroduce them. For text columns prefer trim (remove surrounding whitespace). "
              "Use numeric only for numeric text, datetime only for date text. Do not convert identifiers or protected fields. "
              "NEVER fabricate financial amounts, dates, timestamps, keys or identifiers; nulls can be legitimate. "
              "fill_constant is ONLY allowed for noncritical categorical fields with value Unknown. "
              "Use a lowercase dataset name and version 1.0. Your rules require human approval. "
              "Exact allowed table-to-column catalog: " + json.dumps(allowed))
    for attempt in range(3):
        try:
            proposal = request_json(prompt, metadata, Proposal, model)
            for rule in proposal.rules:
                if rule.table not in allowed or rule.column not in allowed[rule.table]:
                    raise ValueError("Rule references an absent table or column")
            break
        except ValueError:
            if attempt == 2:
                raise ValueError("Local Llama 3 did not return valid conservative rules after three attempts") from None
            prompt += " Your previous response failed validation. Use only exact catalog names and conservative allowed actions."
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
    return output


def approve(proposal_path: Path, reviewer: str, output: Path) -> Path:
    if not reviewer.strip():
        raise ValueError("A human reviewer name is required")
    proposal = Proposal.model_validate_json(proposal_path.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"proposal_sha256": digest(proposal), "reviewer": reviewer.strip(), "approved_at": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    return output


def check_approval(proposal: Proposal, approval_path: Path) -> dict:
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    return validate_approval(proposal, approval)


def validate_approval(proposal: Proposal, approval: dict) -> dict:
    if approval.get("proposal_sha256") != digest(proposal) or not approval.get("reviewer") or not approval.get("approved_at"):
        raise ValueError("Missing approval or proposal changed after human approval")
    return approval
