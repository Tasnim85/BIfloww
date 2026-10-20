"""Contract 2: the "plug". Every agent exposes run(ctx: RunContext) -> AgentResult."""
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"  # e.g. cleaning routed a missing amount to a human


class RunContext(BaseModel):
    """What the orchestrator gives an agent when it starts it."""
    run_id: str                                  # e.g. "run_001"
    agent: str                                   # e.g. "etl"
    inputs: dict[str, Path]                      # name -> file written by an upstream agent
    output_dir: Path                             # where this agent writes, e.g. runs/run_001/etl/
    params: dict = Field(default_factory=dict)   # optional settings (thresholds, KPI name...)


class AgentResult(BaseModel):
    """What an agent gives back to the orchestrator when it finishes."""
    run_id: str
    agent: str
    status: AgentStatus
    outputs: dict[str, Path] = Field(default_factory=dict)  # name -> file it wrote
    message: str = ""                                       # short human-readable summary
