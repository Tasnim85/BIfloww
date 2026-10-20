"""The "why?" agent (BO3): answers a free question about a run, from the evidence.

    python -m auditor.why "Pourquoi la comparaison août/juillet a-t-elle été bloquée ?"
    python -m auditor.why --journal runs/demo_journal.db "D'où vient le chiffre d'affaires ?"

How it works (a small tool-using agent):
  1. The LLM receives the question and READ-ONLY tools (auditor/tools.py), declared
     with the provider's NATIVE tool calling (what gpt-oss and Llama are trained for).
  2. Each turn it calls one tool, or final_answer(answer, citations). If it returns
     nothing, and always on the last turn, a WRITER call turns the collected tool
     results into the answer (prompts/why_writer.yaml).
  3. The final answer is VERIFIED before it is accepted:
       - every number must appear in a tool result of this conversation;
       - every cited journal entry must exist AND have been returned by a tool.
     If not, the agent gets one chance to correct itself, then we fall back.
  4. Fallback (no LLM, failed checks, too many steps): a deterministic answer that
     lists the journal entries matching the question. Never an invented answer.
  5. Everything is journaled: each LLM call (by chat_tools) and the final answer.
The prompt lives in prompts/why_agent.yaml.
"""
import argparse
import re
from pathlib import Path

from pydantic import BaseModel, Field

from auditor.tools import Toolbox
from contracts.agent import RunContext
from contracts.audit import DEFAULT_JOURNAL, AuditEvent, log_event
from contracts.factcheck import allowed_numbers, unsupported_numbers
from contracts.llm import LLMConfig, LLMUnavailable, ToolCall, chat_json, chat_tools, tool_message
from contracts.pipeline import REPO_ROOT, RUNS_ROOT
from contracts.prompts import load_prompt
from contracts.xai import WhyAnswer

PROMPT_NAME = "why_agent"
WRITER_PROMPT = "why_writer"
MAX_STEPS = 8
_ENTRY_REF = re.compile(r"#(\d+)|\"entry_id\":\s*(\d+)")

class AgentStep(BaseModel):
    """One move of the agent, whatever the provider's wire format."""
    thought: str = ""
    action: str                                   # a tool name, or "answer"
    args: dict = Field(default_factory=dict)
    answer: str = ""
    citations: list[int] = Field(default_factory=list)

    @classmethod
    def from_call(cls, call: ToolCall) -> "AgentStep":
        if call.name == "final_answer":
            text = str(call.args.get("answer", ""))
            cites = call.args.get("citations") or []
            ids = [int(str(c).lstrip("#")) for c in cites if str(c).lstrip("#").isdigit()] \
                if isinstance(cites, list) else []
            # a plain-text answer has no citations list: take the "(#6)" written in the text
            return cls(action="answer", answer=text, citations=ids or sorted(_entry_ids(text)))
        return cls(action=call.name, args=call.args)


def _entry_ids(text: str) -> set[int]:
    return {int(a or b) for a, b in _ENTRY_REF.findall(text)}


JOURNAL_TOOLS = {"search_journal", "get_entry"}


def verify(step: AgentStep, question: str, outputs: list[tuple[str, str]], entry_text) -> list[str]:
    """Problems with a final answer. Empty list = accepted.

    outputs: (tool name, tool output) of this conversation.
    entry_text: function entry_id -> full text of that journal entry.
    Checks, in order:
      1. the agent investigated (at least one tool call);
      2. every cited entry was returned by a tool (no citation from memory);
      3. every number appears in a tool result (no invented figure);
      4. every number taken from the journal appears in an entry the answer CITES
         (a citation must really support the claim; reports, lineage and KPI
         definitions count as sources of their own).
    """
    if not step.answer.strip():
        return ["the answer is empty: write the answer text and its citations"]
    if not outputs:
        return ["no tool was called: investigate with the tools before answering"]
    corpus = "\n".join(text for _, text in outputs)
    problems = []
    cited = set(step.citations) | _entry_ids(step.answer)
    unseen = sorted(cited - _entry_ids(corpus))
    if unseen:
        problems.append(f"cited entries never returned by a tool: {unseen}")
    bad = unsupported_numbers(step.answer, allowed_numbers(corpus, question))
    if bad:
        problems.append(f"numbers not found in any tool result: {bad}")
    if not step.citations and unsupported_numbers(step.answer, set()):
        problems.append("an answer with figures must cite journal entries")
        return problems
    other_sources = "\n".join(text for name, text in outputs if name not in JOURNAL_TOOLS)
    cited_text = "\n".join(entry_text(i) for i in sorted(cited - set(unseen)))
    weak = [n for n in unsupported_numbers(step.answer, allowed_numbers(other_sources, cited_text, question))
            if n not in bad]
    if weak:
        problems.append(f"numbers {weak} are not in the entries you cited: cite the entry each "
                        f"number comes from (use get_entry to check)")
    return problems


ROUTINE = {"OK", "PASSED", "computed in SQL"}


def fallback_answer(tools: Toolbox, question: str, reason: str) -> tuple[str, list[int]]:
    """Deterministic answer: the journal entries matching the question's words, or else
    the run's notable decisions (anything that is not a routine OK/PASSED)."""
    words = " ".join(w for w in re.findall(r"\w+", question.lower()) if len(w) > 3)
    found = tools.call("search_journal", {"text": words, "limit": 10})
    if found.startswith("No matching"):
        notable = [e for e in tools._events() if e.decision not in ROUTINE][:12]
        found = "\n".join(f"#{e.entry_id} {e.agent}.{e.step}: {e.decision}" for e in notable)
        intro = "No entry matches the question's words; notable decisions of the run"
    else:
        intro = "Decisions recorded for this run that match the question"
    return (f"Automatic answer ({reason[:160]}). {intro}:\n{found}"), sorted(_entry_ids(found))


class FinalAnswer(BaseModel):
    answer: str = Field(description="The answer for the manager, citing entries as (#12).")
    citations: list[int] = Field(default_factory=list, description="Journal entry ids used.")


class WhyAgent:
    """Two roles:
      - the INVESTIGATOR calls tools (native tool calling, self.llm);
      - the WRITER turns the collected tool results into the final answer (structured
        JSON, self.writer). It takes over when the investigator returns nothing, and
        always on the last turn: gpt-oss investigates well but often fails to conclude
        with a tool call.
    Every answer, whoever wrote it, goes through verify().
    """

    def __init__(self, run_id: str, journal: Path = DEFAULT_JOURNAL, runs_root: Path = RUNS_ROOT,
                 repo_root: Path = REPO_ROOT, config: LLMConfig | None = None,
                 language: str = "French", max_steps: int = MAX_STEPS, llm=chat_tools, writer=chat_json):
        self.run_id, self.journal, self.language, self.max_steps = run_id, Path(journal), language, max_steps
        self.runs_root, self.repo_root = runs_root, repo_root
        self.config, self.llm, self.writer = config or LLMConfig(), llm, writer

    def _write(self, question: str, outputs: list[tuple[str, str]], ctx, feedback: str | None) -> AgentStep:
        prompt = load_prompt(WRITER_PROMPT)
        results = "\n\n".join(f"RESULT of {name}:\n{text}" for name, text in outputs) or "(no tool result)"
        user = f"QUESTION: {question}\n\nTOOL RESULTS:\n{results}"
        if feedback:
            user += f"\n\nA previous draft was REFUSED by the fact check: {feedback}"
        out = self.writer(prompt.render(language=self.language), user, FinalAnswer,
                          prompt_version=prompt.ref, ctx=ctx, step="why_writer", config=self.config)
        return AgentStep(action="answer", answer=out.answer,
                         citations=out.citations or sorted(_entry_ids(out.answer)))

    def ask(self, question: str) -> WhyAnswer:
        tools = Toolbox(self.run_id, self.journal, self.runs_root, self.repo_root)
        ctx = RunContext(run_id=self.run_id, agent="auditor", inputs={}, output_dir=Path("."),
                         journal=self.journal)                  # only used to journal LLM calls
        prompt = load_prompt(PROMPT_NAME)
        messages = [{"role": "system", "content": prompt.render(
                        run_id=self.run_id, language=self.language, max_steps=str(self.max_steps))},
                    {"role": "user", "content": f"QUESTION: {question}"}]
        outputs: list[tuple[str, str]] = []
        rejected: list[str] = []
        result, use_writer, feedback = None, False, None

        for turn in range(self.max_steps):
            call = None
            try:
                if use_writer or turn == self.max_steps - 1:
                    step = self._write(question, outputs, ctx, feedback)
                else:
                    call, assistant = self.llm(messages, tools.schemas(), prompt_version=prompt.ref,
                                               ctx=ctx, step="why_agent", config=self.config)
                    messages.append(assistant)
                    step = AgentStep.from_call(call)
                    if step.action == "answer" and not step.answer.strip():
                        rejected.append("the investigator returned an empty answer: the writer takes over")
                        messages.append(tool_message(call, "Empty answer."))
                        use_writer = True
                        continue
            except LLMUnavailable as e:
                rejected.append(f"LLM unavailable: {e}")
                break
            except Exception as e:                              # malformed answer, etc.
                rejected.append(f"invalid LLM answer: {type(e).__name__}: {str(e)[:120]}")
                break

            if step.action == "answer":
                problems = verify(step, question, outputs, tools.entry_text)
                if not problems:
                    result = (step.answer, sorted(set(step.citations)))
                    break
                feedback = "; ".join(problems)
                rejected.append(feedback)
                if call is not None:
                    messages.append(tool_message(call, f"Your answer was REFUSED by the fact check: {feedback}. "
                                                       f"Use only what the tools returned, then answer again."))
                continue

            out = tools.call(step.action, step.args)
            outputs.append((step.action, out))
            messages.append(tool_message(call, f"RESULT of {step.action}({step.args}):\n{out}"))
        else:
            rejected.append(f"no verified answer within {self.max_steps} steps")

        if result:
            answer = WhyAnswer(run_id=self.run_id, question=question, answer=result[0],
                               citations=result[1], source=f"llm:{self.config.model}", verified=True,
                               tool_calls=tools.calls, rejected=rejected)
        else:
            text, cites = fallback_answer(tools, question, rejected[-1] if rejected else "no answer")
            answer = WhyAnswer(run_id=self.run_id, question=question, answer=text, citations=cites,
                               source="template", verified=True, tool_calls=tools.calls,
                               rejected=rejected)
        log_event(AuditEvent(run_id=self.run_id, agent="auditor", step="why_answer",
                             decision=f"answered ({answer.source})", rule_version=prompt.ref,
                             evidence={"question": question, "citations": answer.citations,
                                       "tool_calls": [c["tool"] for c in answer.tool_calls],
                                       "rejected_drafts": rejected, "answer": answer.answer[:1000]}),
                  self.journal)
        return answer


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--run", default="run_001")
    p.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    p.add_argument("--language", default="French")
    args = p.parse_args()

    a = WhyAgent(args.run, journal=args.journal, language=args.language).ask(args.question)
    print(f"Q: {a.question}\n")
    print(f"[{a.source}] {a.answer}\n")
    print("Citations:", ", ".join(f"#{c}" for c in a.citations) or "none")
    print("Tools used:", " -> ".join(f"{c['tool']}({c['args']})" for c in a.tool_calls) or "none")
    for r in a.rejected:
        print("Refused draft:", r)


if __name__ == "__main__":
    main()
