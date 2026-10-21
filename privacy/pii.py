"""Public entrypoint specified by contracts.pipeline."""
from contracts import AgentResult, RunContext
from bo2.contract_adapter import execute
from privacy.agent import run as engine


def run(ctx: RunContext) -> AgentResult:
    return execute(ctx, engine)
