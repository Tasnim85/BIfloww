"""Tests of step 4: the "why?" agent and the Auditor agent.   python -m pytest tests/test_why.py -v

A scripted fake LLM plays precise scenarios; no API key is used.
Every test writes its own journal in a temporary folder.
"""
import sqlite3
from pathlib import Path

import pytest

from auditor.agent import run as run_auditor
from auditor.tools import Toolbox
from auditor.why import AgentStep, WhyAgent, verify
from comparisons.checker import run as run_comparisons
from contracts.agent import AgentStatus, RunContext
from contracts.audit import AuditEvent, log_event, read_events
from contracts.llm import LLMUnavailable, ToolCall
from contracts.pipeline import context_for

REAL = context_for("comparisons", "run_001")
pytestmark = pytest.mark.skipif(
    not Path(REAL.inputs["coverage"]).exists() or not Path("runs/run_001/lineage/lineage.json").exists(),
    reason="run make_fake_inputs and contracts.examples.install first")


@pytest.fixture
def journal(tmp_path) -> Path:
    """A journal holding a real run of the comparisons agent (outputs go to tmp)."""
    j = tmp_path / "journal.db"
    log_event(AuditEvent(run_id="run_001", agent="etl", step="build_fact_payments",
                         decision="PASSED", evidence={"rows_before": 103886, "rows_after": 100756}), j)
    ctx = RunContext(run_id="run_001", agent="comparisons", inputs=dict(REAL.inputs),
                     output_dir=tmp_path / "out", params={"llm": False}, journal=j)
    run_comparisons(ctx)
    return j


def entry_id(journal: Path, step: str) -> int:
    return next(e.entry_id for e in read_events(journal) if e.step == step)


class ScriptedLLM:
    """Plays the given moves in order, in the native tool-calling format; records what
    the agent sent back (the last message: question, tool result or refusal)."""
    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def __call__(self, messages, tools, **kw):
        self.seen.append(messages[-1]["content"])
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if step["action"] == "answer":
            call = ToolCall(name="final_answer", id=f"c{len(self.seen)}",
                            args={"answer": step.get("answer", ""), "citations": step.get("citations", [])})
        else:
            call = ToolCall(name=step["action"], args=step.get("args", {}), id=f"c{len(self.seen)}")
        return call, {"role": "assistant", "content": "", "tool_calls": [
            {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": "{}"}}]}


class ScriptedWriter:
    """Plays the writer role: returns the given (answer, citations) in order."""
    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def __call__(self, system, user, schema, **kw):
        self.seen.append(user)
        if not self.answers:
            raise LLMUnavailable("no writer answer scripted")
        text, cites = self.answers.pop(0)
        return schema(answer=text, citations=cites)


def agent(journal, llm, writer=None, max_steps=6) -> WhyAgent:
    return WhyAgent("run_001", journal=journal, llm=llm, writer=writer or ScriptedWriter(),
                    max_steps=max_steps)


Q = "Pourquoi la comparaison août/juillet a-t-elle été bloquée ?"


def test_good_answer_is_accepted_with_citations(journal):
    cov = entry_id(journal, "check_coverage")
    llm = ScriptedLLM(
        {"thought": "find the check", "action": "search_journal", "args": {"step": "check_coverage"}},
        {"thought": "full evidence", "action": "get_entry", "args": {"entry_id": cov}},
        {"thought": "done", "action": "answer", "citations": [cov],
         "answer": f"L'agent comparisons a bloqué la comparaison (#{cov}) : août n'est complet que "
                   f"jusqu'au 2018-08-23, entre 1 et 99 commandes par jour ensuite contre 195."})
    a = agent(journal, llm).ask(Q)
    assert a.source.startswith("llm:") and a.verified and a.citations == [cov]
    assert [c["tool"] for c in a.tool_calls] == ["search_journal", "get_entry"]
    assert "RESULT of search_journal" in llm.seen[1]              # the tool output was fed back
    last = read_events(journal)[-1]
    assert last.step == "why_answer" and last.evidence["citations"] == [cov]


def test_a_number_the_agent_has_not_seen_is_refused(journal):
    """195 is in the journal, but only in the part search_journal cuts off: unseen = refused."""
    cov = entry_id(journal, "check_coverage")
    llm = ScriptedLLM(
        {"thought": "s", "action": "search_journal", "args": {"step": "check_coverage"}},
        {"thought": "a", "action": "answer", "citations": [cov], "answer": f"Contre 195 (#{cov})."},
        {"thought": "look", "action": "get_entry", "args": {"entry_id": cov}},
        {"thought": "a", "action": "answer", "citations": [cov], "answer": f"Contre 195 (#{cov})."})
    a = agent(journal, llm).ask(Q)
    assert a.source.startswith("llm:") and "195" in a.rejected[0]


def test_invented_number_is_refused_then_corrected(journal):
    cov = entry_id(journal, "check_coverage")
    llm = ScriptedLLM(
        {"thought": "search", "action": "search_journal", "args": {"step": "check_coverage"}},
        {"thought": "answer", "action": "answer", "citations": [cov],
         "answer": f"Août a perdu 12.5% de ses données (#{cov})."},          # 12.5 is invented
        {"thought": "fix", "action": "answer", "citations": [cov],
         "answer": f"Août n'est complet que jusqu'au 2018-08-23 (#{cov})."})
    a = agent(journal, llm).ask(Q)
    assert a.source.startswith("llm:") and "12.5" not in a.answer
    assert len(a.rejected) == 1 and "12.5" in a.rejected[0]
    assert "REFUSED" in llm.seen[2]                                 # the agent was told why


def test_citing_an_unseen_entry_ends_in_fallback(journal):
    bad = {"thought": "answer", "action": "answer", "citations": [999], "answer": "Voir (#999)."}
    llm = ScriptedLLM({"thought": "s", "action": "search_journal", "args": {"step": "check_unit"}},
                      bad, bad, bad)
    a = agent(journal, llm).ask(Q)
    assert a.source == "template" and 999 not in a.citations
    assert any("never returned by a tool" in r for r in a.rejected)


def test_unknown_tool_is_reported_to_the_agent(journal):
    llm = ScriptedLLM({"thought": "?", "action": "get_entry", "args": {"wrong": 1}},
                      {"thought": "ok", "action": "answer", "answer": "Je ne trouve pas la réponse."})
    a = agent(journal, llm).ask(Q)
    assert "ERROR: wrong arguments" in llm.seen[1]
    assert a.source.startswith("llm:") and a.citations == []


def test_no_llm_gives_a_deterministic_answer(journal):
    a = agent(journal, ScriptedLLM(LLMUnavailable("no key"))).ask("coverage")
    assert a.source == "template" and "check_coverage" in a.answer
    assert entry_id(journal, "check_coverage") in a.citations


def test_identifiers_are_not_figures(journal):
    cov = entry_id(journal, "check_coverage")
    llm = ScriptedLLM(
        {"thought": "s", "action": "search_journal", "args": {"step": "check_coverage"}},
        {"thought": "a", "action": "answer", "citations": [cov],
         "answer": f"Dans run_001, la règle comparability-rules@1.0 a bloqué la comparaison (#{cov})."})
    assert agent(journal, llm).ask(Q).source.startswith("llm:")


def test_wrong_agent_filter_lists_the_real_agents(journal):
    out = Toolbox("run_001", journal).call("search_journal", {"agent": "run_001"})
    assert "Agents in this run:" in out and "comparisons" in out


def test_reports_give_entry_ids_to_cite(journal):
    out = Toolbox("run_001", journal).call("read_report", {"name": "comparison"})
    assert "Journal entries behind this report: #" in out


def test_verify_rules():
    entries = {7: '{"step": "check_coverage", "evidence": {"usual": 195}}', 13: '{"step": "verdict"}'}
    outputs = [("search_journal", "#7 check_coverage: BLOCKING | usual 195\n#13 verdict: needs_review")]
    text = lambda i: entries.get(i, "")                                    # noqa: E731
    ok = AgentStep(thought="", action="answer", citations=[7], answer="Bloqué (#7), 195 par jour.")
    assert verify(ok, "q", outputs, text) == []
    no_cite = AgentStep(thought="", action="answer", answer="195 par jour.")
    assert "must cite" in verify(no_cite, "q", outputs, text)[0]
    wrong_cite = AgentStep(thought="", action="answer", citations=[13], answer="Bloqué (#13), 195 par jour.")
    assert "not in the entries you cited" in verify(wrong_cite, "q", outputs, text)[0]
    no_tool = AgentStep(thought="", action="answer", answer="Pas d'information.")
    assert "no tool was called" in verify(no_tool, "q", [], text)[0]


def test_answer_without_investigation_is_refused(journal):
    llm = ScriptedLLM({"thought": "lazy", "action": "answer", "answer": "Pas d'information."},
                      {"thought": "look", "action": "read_report", "args": {"name": "anomaly_explanation"}},
                      {"thought": "a", "action": "answer", "answer": "Voir les lignes les plus anormales."})
    a = agent(journal, llm).ask("Pourquoi le paiement le plus anormal a-t-il été signalé ?")
    assert a.source.startswith("llm:") and "no tool was called" in a.rejected[0]
    assert a.tool_calls[0]["tool"] == "read_report"


def test_citing_the_verdict_instead_of_the_check_is_refused(journal):
    cov, verdict = entry_id(journal, "check_coverage"), entry_id(journal, "comparison_verdict")
    llm = ScriptedLLM(
        {"thought": "s", "action": "search_journal", "args": {"agent": "comparisons"}},
        {"thought": "a", "action": "answer", "citations": [verdict],
         "answer": f"Bloqué (#{verdict}) : complet jusqu'au 2018-08-23."},
        {"thought": "a", "action": "answer", "citations": [cov],
         "answer": f"Bloqué (#{cov}) : complet jusqu'au 2018-08-23."})
    a = agent(journal, llm).ask(Q)
    assert a.citations == [cov] and "not in the entries you cited" in a.rejected[0]


# ---- tools ---------------------------------------------------------------------------
def test_lineage_tool_walks_back_to_the_raw_csv(journal):
    out = Toolbox("run_001", journal).call("trace_lineage", {"node": "kpi:Revenue@2.0"})
    assert "olist_order_payments_dataset.csv / payment_value" in out
    assert "filtered order_status == 'delivered'" in out


def test_tools_never_crash(journal):
    t = Toolbox("run_001", journal)
    assert t.call("drop_table", {}).startswith("ERROR: unknown tool")
    assert t.call("get_entry", {"entry_id": 99999}).startswith("ERROR")
    assert t.call("read_report", {"name": "nonsense"}).startswith("ERROR")
    assert len(t.calls) == 3


# ---- the Auditor agent ---------------------------------------------------------------
def test_auditor_agent_writes_its_three_outputs(journal):
    res = run_auditor(context_for("auditor", "run_001", journal=journal))
    assert res.status == AgentStatus.SUCCESS
    assert set(res.outputs) == {"explanations", "integrity", "drift"}
    assert all(Path(p).exists() for p in res.outputs.values())


def test_auditor_fails_when_the_journal_was_tampered(journal):
    con = sqlite3.connect(journal)
    con.execute("DROP TRIGGER journal_no_update")
    con.execute("UPDATE journal SET decision = 'HACKED' WHERE entry_id = 2")
    con.commit()
    con.close()
    res = run_auditor(context_for("auditor", "run_001", journal=journal))
    assert res.status == AgentStatus.FAILED and "tampered" in res.message


def test_plain_text_answer_keeps_the_citations_written_in_it(journal):
    from auditor.why import AgentStep
    step = AgentStep.from_call(ToolCall(name="final_answer", args={"answer": "Bloqué (#6) puis (#11)."}))
    assert step.citations == [6, 11]


def test_empty_answer_hands_over_to_the_writer(journal):
    """Seen with Groq: after investigating, gpt-oss sends an empty message."""
    cov = entry_id(journal, "check_coverage")
    llm = ScriptedLLM({"action": "search_journal", "args": {"step": "check_coverage"}},
                      {"action": "answer", "answer": ""})
    writer = ScriptedWriter((f"Bloqué (#{cov}) jusqu'au 2018-08-23.", [cov]))
    a = agent(journal, llm, writer).ask(Q)
    assert a.source.startswith("llm:") and a.citations == [cov]
    assert "empty" in a.rejected[0]
    assert "check_coverage" in writer.seen[0]                  # the writer got the tool results


def test_refused_writer_draft_gets_the_reason(journal):
    cov = entry_id(journal, "check_coverage")
    llm = ScriptedLLM({"action": "search_journal", "args": {"step": "check_coverage"}},
                      {"action": "answer", "answer": ""})
    writer = ScriptedWriter(("Il manque 12.5% des données.", [cov]),           # invented figure
                            (f"Bloqué (#{cov}) jusqu'au 2018-08-23.", [cov]))
    a = agent(journal, llm, writer).ask(Q)
    assert a.source.startswith("llm:") and "12.5" in a.rejected[1]
    assert "REFUSED" in writer.seen[1]


def test_last_turn_is_always_the_writer(journal):
    llm = ScriptedLLM(*[{"action": "search_journal", "args": {"text": "coverage"}}] * 3)
    writer = ScriptedWriter(("Je ne trouve pas la réponse dans le journal.", []))
    a = agent(journal, llm, writer, max_steps=4).ask(Q)
    assert len(llm.seen) == 3 and len(writer.seen) == 1 and a.source.startswith("llm:")


def test_empty_answer_never_accepted():
    from auditor.why import AgentStep
    assert "empty" in verify(AgentStep(action="answer", answer="  "), "q", [("x", "y")], lambda i: "")[0]


def test_writer_sees_in_full_the_entries_the_investigator_only_glimpsed(journal):
    """Seventh test: the investigator opened only the verdict; the writer must see the check."""
    cov, verdict = entry_id(journal, "check_coverage"), entry_id(journal, "comparison_verdict")
    llm = ScriptedLLM({"action": "search_journal", "args": {"agent": "comparisons"}},
                      {"action": "get_entry", "args": {"entry_id": verdict}},
                      {"action": "answer", "answer": ""})
    # 195 is cut from the search line: only the expanded entry #cov shows it
    writer = ScriptedWriter((f"Bloqué (#{cov}) : au-delà du 2018-08-23, moins de 195 commandes par jour.", [cov]))
    a = agent(journal, llm, writer).ask(Q)
    assert a.source.startswith("llm:"), a.rejected
    assert f"#{cov} (full entry)" in writer.seen[0]
    assert "expanded_entry" not in [c["tool"] for c in a.tool_calls]     # not a tool the LLM called


def test_writer_gets_the_checks_behind_a_verdict_the_search_never_showed(journal):
    """Eighth test: only the verdict was found; the blocking check must reach the writer."""
    cov, verdict = entry_id(journal, "check_coverage"), entry_id(journal, "comparison_verdict")
    llm = ScriptedLLM({"action": "get_entry", "args": {"entry_id": verdict}},
                      {"action": "answer", "answer": ""})
    writer = ScriptedWriter((f"Bloqué par le contrôle de couverture (#{cov}) : complet jusqu'au 2018-08-23.", [cov]))
    a = agent(journal, llm, writer).ask(Q)
    assert a.source.startswith("llm:") and a.citations == [cov], a.rejected
    seen = writer.seen[0]
    assert seen.index(f"#{cov} (full entry)") < seen.index("check_unit") if "check_unit" in seen else True
