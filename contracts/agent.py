"""Contract 2: the "plug". Every agent is a function run(ctx: RunContext) -> AgentResult.

The orchestrator (Samar) only knows this function. It never imports anything else
from an agent's package.
"""
from enum import Enum
from pathlib import Path

from pydantic import Field

from contracts.audit import DEFAULT_JOURNAL, AuditEvent, JournalEntry, log_event
from contracts.common import Contract


class AgentStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"              # the orchestrator stops everything that depends on this step
    NEEDS_REVIEW = "needs_review"  # a human must confirm (new LLM rules, comparison fix...)
    SKIPPED = "skipped"            # nothing to do (e.g. no comparison in the question)


class RunContext(Contract):
    """What the orchestrator gives an agent when it starts it."""
    run_id: str                                  # e.g. "run_001"
    agent: str                                   # an AgentName value, e.g. "etl"
    inputs: dict[str, Path]                      # input key -> file or folder (see pipeline.py)
    output_dir: Path                             # where this agent writes: runs/<run_id>/<agent>/
    params: dict = Field(default_factory=dict)   # optional settings (thresholds, top_k...)
    journal: Path = DEFAULT_JOURNAL              # the shared audit journal

    def output(self, key: str) -> Path:
        """Path where this agent must write its output `key` (fixed in pipeline.py)."""
        from contracts.pipeline import STEPS   # local import: pipeline imports this file
        return self.output_dir / STEPS[self.agent].outputs[key]

    def log(self, step: str, decision: str, *, inputs: list[str] | None = None,
            outputs: list[str] | None = None, rule_version: str | None = None,
            evidence: dict | None = None) -> JournalEntry:
        """Shortcut: write one audit event for this run and this agent."""
        return log_event(AuditEvent(
            run_id=self.run_id, agent=self.agent, step=step, decision=decision,
            inputs=inputs or [], outputs=outputs or [], rule_version=rule_version,
            evidence=evidence or {}), self.journal)


class AgentResult(Contract):
    """What an agent gives back to the orchestrator when it finishes."""
    run_id: str
    agent: str
    status: AgentStatus
    outputs: dict[str, Path] = Field(default_factory=dict)  # output key -> file it wrote
    message: str = ""                                       # one human-readable sentence
