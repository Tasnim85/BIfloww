"""Step 6: the insight agent, tested with a FAKE Groq (no key, no internet needed).
We replace contracts.llm._post, the only function that talks to the network."""
import json

import pytest

import contracts.llm as llm
from analysis.analyst import run
from analysis.dev_warehouse import build
from analysis.insight_agent import Facts, InsightDraft, check_draft
from contracts import AgentStatus, context_for, read_events
from contracts.registry import read_output


def tool_call(name, args):
    return {"choices": [{"message": {"content": "", "tool_calls": [{
        "id": f"call_{name}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def text(content):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def fake_groq(monkeypatch):
    """Answers the scripted replies in order and keeps every request it received."""
    monkeypatch.setenv("BIFLOW_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    sent, replies = [], []

    def fake_post(url, payload, timeout, headers=None):
        sent.append(payload)
        return replies.pop(0)
    monkeypatch.setattr(llm, "_post", fake_post)
    return sent, replies


def run_agent(tmp_path, run_id="i1"):
    build(run_id, tmp_path)
    journal = tmp_path / "journal.db"
    out = run(context_for("analysis", run_id, runs_root=tmp_path, journal=journal))
    return out, read_output(out.outputs["result"], "analysis.result"), read_events(journal)


# Facts of the dev warehouse: F1 total, F2 RJ, F3 SP (asked by Sarra), then payment_type
# when the explorer asks for it: F4 boleto, F5 credit_card, F6 debit_card, F7 voucher.

def test_llm_insights_are_fact_checked(tmp_path, fake_groq):
    sent, replies = fake_groq
    replies += [
        tool_call("breakdown", {"dimension": "payment_type"}),   # explorer, turn 1
        tool_call("done", {}),                                    # explorer, turn 2
        text(json.dumps({"insights": [                            # writer
            {"text": "SP drove the growth: 280.00 BRL, +180.0% vs July.", "facts": ["F3"]},
            {"text": "Revenue will reach 999 BRL next month.", "facts": ["F1"]},     # invented
        ]})),
    ]
    out, result, events = run_agent(tmp_path)

    assert out.status == AgentStatus.SUCCESS
    assert [i.text for i in result.insights] == ["SP drove the growth: 280.00 BRL, +180.0% vs July."]
    assert "280.00" in result.insights[0].evidence["F3"]          # the fact behind the sentence
    # the tool offered only the KPI's allowed dimensions, and computed payment_type for real
    spec = sent[0]["tools"][0]["function"]["parameters"]["properties"]["dimension"]
    assert spec["enum"] == ["payment_type", "order_month"]        # customer_state is already given
    assert sent[0]["tool_choice"]["function"]["name"] == "breakdown"   # turn 1: must explore
    assert "payment_type = credit_card" in sent[1]["messages"][-1]["content"]
    steps = [e.step for e in events]
    assert "llm:insight_explorer" in steps and "llm:insight_writer" in steps
    refused = [e for e in events if e.step == "insight_refused"]
    assert len(refused) == 1 and "999" in refused[0].decision


def test_forbidden_dimension_is_refused_by_the_tool(tmp_path, fake_groq):
    sent, replies = fake_groq
    replies += [tool_call("breakdown", {"dimension": "product_category"}),   # not allowed for Revenue
                tool_call("done", {}),
                text(json.dumps({"insights": [{"text": "Revenue grew by +100.00 BRL.", "facts": ["F1"]}]}))]
    out, result, _ = run_agent(tmp_path)
    assert sent[1]["messages"][-1]["content"].startswith("Refused")
    assert out.status == AgentStatus.SUCCESS and len(result.insights) == 1


def test_no_llm_falls_back_to_deterministic_insights(tmp_path, monkeypatch):
    def down(*a, **k):
        raise llm.LLMUnavailable("no internet")
    monkeypatch.setattr(llm, "_post", down)
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    out, result, events = run_agent(tmp_path)
    assert out.status == AgentStatus.SUCCESS                       # the LLM never stops the pipeline
    assert result.insights and result.insights[0].text.startswith("SP makes")
    written = [e for e in events if e.step == "insights_written"][0]
    assert written.evidence["source"] == "fallback"


def test_check_draft():
    facts = Facts()
    facts.add("customer_state = SP: current 280.00 BRL, previous 100.00 BRL, change +180.00 BRL (+180.0%).")
    assert check_draft(InsightDraft(text="SP: 280 BRL, +180%.", facts=["F1"]), facts) is None
    assert "unknown" in check_draft(InsightDraft(text="SP grew.", facts=["F9"]), facts)
    assert "no fact" in check_draft(InsightDraft(text="SP grew.", facts=[]), facts)
    assert "281" in check_draft(InsightDraft(text="SP: 281 BRL.", facts=["F1"]), facts)
