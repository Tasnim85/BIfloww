"""Step 5: the whole agent, called exactly as the orchestrator will call it."""
import pandas as pd
import pytest

import contracts.llm as llm

from analysis.analyst import run
from analysis.dev_warehouse import EXPECTED, build
from contracts import AgentStatus, context_for, read_events, verify_journal
from contracts.registry import read_output


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """These tests check the numbers, not Groq: the LLM is unreachable, so the agent uses its
    deterministic insights (and no test sends a request, even with a key in .env)."""
    def down(*args, **kwargs):
        raise llm.LLMUnavailable("LLM disabled in this test")
    monkeypatch.setattr(llm, "_post", down)


def test_agent_writes_a_validated_result_and_logs_it(tmp_path):
    build("t1", tmp_path)
    journal = tmp_path / "journal.db"
    out = run(context_for("analysis", "t1", runs_root=tmp_path, journal=journal))

    assert out.status == AgentStatus.SUCCESS
    result = read_output(out.outputs["result"], "analysis.result")   # valid against the contract
    assert result.kpi == "Revenue@2.0"
    assert result.value_current == EXPECTED["2018-08"]["total"]
    assert result.value_previous == EXPECTED["2018-07"]["total"]
    assert all(c.passed for c in result.validations)

    df = pd.read_parquet(out.outputs["data"])
    assert list(df.columns) == ["customer_state", "period", "value"]   # the format agreed in the README

    steps = [e.step for e in read_events(journal)]
    assert steps[0] == "kpi_version_chosen" and steps[-1] == "result_written"
    assert "check_join_multiplicity" in steps
    assert verify_journal(journal).ok          # nobody tampered with the journal


def test_unknown_kpi_fails_cleanly(tmp_path):
    build("t2", tmp_path)
    req_path = tmp_path / "t2/request/analysis_request.json"
    req_path.write_text(req_path.read_text().replace('"metric": "Revenue"', '"metric": "Profit"'))
    out = run(context_for("analysis", "t2", runs_root=tmp_path, journal=tmp_path / "j.db"))
    assert out.status == AgentStatus.FAILED
    assert "Profit" in out.message
