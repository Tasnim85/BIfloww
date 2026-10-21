"""Step 6: the insight agent (Rabeb), a real LLM agent (Groq by default, see contracts/llm.py).

Two roles, like Tasnim's "why?" agent:
  EXPLORER  chooses which breakdowns to look at by calling ONE tool: breakdown(dimension).
            The tool is Python: it compiles the SQL from the catalog, runs it and runs the
            BO3-03 checks. The LLM never writes SQL and never computes a number.
  WRITER    turns the numbered facts (F1, F2...) into short insights that cite their facts.

Each insight then goes through the fact check: every number of its sentence must be in the
facts it cites, otherwise it is refused. If the LLM cannot be reached (no key, no internet,
rate limit) we fall back to the deterministic insights of analysis/insights.py: the pipeline
never stops because of the LLM.
"""
import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from analysis.insights import compute_insights
from analysis.sql_compiler import CompileError, CompiledQuery, compile_query
from analysis.validations import run_checks
from contracts.analysis import Insight
from contracts.factcheck import allowed_numbers, unsupported_numbers
from contracts.llm import LLMUnavailable, chat_json, chat_tools, tool_message
from contracts.prompts import load_prompt

MAX_STEPS = 4        # turns of the explorer
MAX_INSIGHTS = 5


class InsightDraft(BaseModel):
    text: str
    facts: list[str] = Field(default_factory=list)      # ids of the facts it uses, e.g. ["F1", "F3"]


class InsightDrafts(BaseModel):
    """What the writer must answer (validated by chat_json)."""
    insights: list[InsightDraft]


class Facts:
    """Numbered facts, all computed by Python. The LLM may only quote them."""

    def __init__(self):
        self.items: dict[str, str] = {}

    def add(self, text: str) -> str:
        fid = f"F{len(self.items) + 1}"
        self.items[fid] = text
        return fid

    def block(self, ids: list[str] | None = None) -> str:
        return "\n".join(f"{i}: {t}" for i, t in self.items.items() if ids is None or i in ids)


def describe(df: pd.DataFrame, dim: str, unit: str) -> list[str]:
    """A breakdown table -> one sentence of numbers per member (current, share, previous, change)."""
    cur = df[df["period"] == "current"].groupby(dim)["value"].sum()
    prev = df[df["period"] == "previous"].groupby(dim)["value"].sum()
    total = float(cur.sum())
    lines = []
    for member in sorted(set(cur.index) | set(prev.index), key=str):
        c, p = float(cur.get(member, 0.0)), float(prev.get(member, 0.0))
        line = f"{dim} = {member}: current {c:,.2f} {unit}"
        if total:
            line += f" ({c / total:.1%} of the current total)"
        if not prev.empty:
            line += f", previous {p:,.2f} {unit}, change {c - p:+,.2f} {unit}"
            if p:
                line += f" ({(c - p) / p:+.1%})"
        lines.append(line + ".")
    return lines


class Explorer:
    """The breakdown tool. Same rules as the main result: catalog SQL + BO3-03 checks."""

    def __init__(self, ctx, con, request, catalog, manifest, receipts, unit: str, facts: Facts):
        self.ctx, self.con, self.request = ctx, con, request
        self.catalog, self.manifest, self.receipts = catalog, manifest, receipts
        self.unit, self.facts, self.seen = unit, facts, set()

    def breakdown(self, dimension: str) -> str:
        if dimension in self.seen:
            return f"Already given above for {dimension}."
        try:
            q = compile_query(self.request.model_copy(update={"dimensions": [dimension]}),
                              self.catalog, self.manifest)
        except CompileError as e:
            self.ctx.log("insight_breakdown", f"refused {dimension}: {e}")
            return f"Refused: {e}"
        df = self.con.execute(q.sql).df()
        totals = df.groupby("period")["value"].sum().to_dict()
        failed = [c.name for c in run_checks(self.con, q, self.manifest, self.receipts, totals)
                  if not c.passed]
        self.ctx.log("insight_breakdown", f"{dimension}: {'FAILED ' + ', '.join(failed) if failed else 'PASSED'}",
                     rule_version=f"kpi:{q.kpi.ref}",
                     evidence={"dimension": dimension, "rows": len(df), "failed_checks": failed})
        if failed:
            return f"Refused: BO3-03 checks failed ({', '.join(failed)}); these numbers cannot be used."
        self.seen.add(dimension)
        ids = [self.facts.add(line) for line in describe(df, dimension, self.unit)]
        return self.facts.block(ids)


def _tools(allowed: list[str]) -> list[dict]:
    return [
        {"name": "breakdown", "description": "The KPI for the same periods, split by one dimension.",
         "parameters": {"type": "object", "required": ["dimension"], "properties": {
             "dimension": {"type": "string", "enum": allowed}}}},
        {"name": "done", "description": "Stop: the facts are enough to explain the result.",
         "parameters": {"type": "object", "properties": {}}},
    ]


def check_draft(draft: InsightDraft, facts: Facts) -> str | None:
    """None if the insight is accepted, otherwise the reason it is refused."""
    if not draft.facts:
        return "cites no fact"
    unknown = [f for f in draft.facts if f not in facts.items]
    if unknown:
        return f"cites unknown facts {unknown}"
    bad = unsupported_numbers(draft.text, allowed_numbers(*(facts.items[f] for f in draft.facts)))
    if bad:
        return f"numbers not in its facts: {bad}"
    return None


def _agent(ctx, con, q: CompiledQuery, request, catalog, manifest, receipts, totals) -> list[Insight]:
    unit, facts = q.kpi.unit, Facts()

    # Facts given for free: the validated total, then the breakdown(s) Sarra asked for.
    cur, prev = float(totals.get("current", 0.0)), totals.get("previous")
    total = f"Total {q.kpi.name}: current {cur:,.2f} {unit} ({request.period.start} to {request.period.end})"
    if prev is not None:
        prev = float(prev)
        total += f", previous {prev:,.2f} {unit}, change {cur - prev:+,.2f} {unit}"
        if prev:
            total += f" ({(cur - prev) / prev:+.1%})"
    facts.add(total + ".")
    explorer = Explorer(ctx, con, request, catalog, manifest, receipts, unit, facts)
    for dim in request.dimensions:
        explorer.breakdown(dim)

    # ---- EXPLORER: the LLM chooses more breakdowns, the tool computes them -------------------
    prompt = load_prompt("analyst_explorer")
    others = [d for d in q.kpi.allowed_dimensions if d not in explorer.seen]   # not given yet
    messages = [{"role": "system", "content": prompt.render(kpi=q.kpi.ref, unit=unit, dimensions=", ".join(others),
                                                            max_steps=MAX_STEPS)},
                {"role": "user", "content": f"Question: {request.question}\n\nFACTS:\n{facts.block()}"}]
    for turn in range(MAX_STEPS if others else 0):
        # Turn 1: the explorer MUST look at one more dimension (it may choose which one).
        # If the provider refuses the forced call, we ask again without forcing.
        try:
            call, assistant = chat_tools(messages, _tools(others), prompt_version=prompt.ref, ctx=ctx,
                                         step="insight_explorer", final_tool="done",
                                         force_tool="breakdown" if turn == 0 else None)
        except LLMUnavailable:
            if turn != 0:
                raise
            call, assistant = chat_tools(messages, _tools(others), prompt_version=prompt.ref, ctx=ctx,
                                         step="insight_explorer", final_tool="done")
        if call.name != "breakdown":
            break
        messages += [assistant, tool_message(call, explorer.breakdown(str(call.args.get("dimension", ""))))]

    # ---- WRITER: insights that cite their facts ----------------------------------------------
    writer = load_prompt("analyst_insights")
    drafts = chat_json(writer.render(kpi=q.kpi.ref, unit=unit, max_insights=MAX_INSIGHTS),
                       f"Question: {request.question}\n\nFACTS:\n{facts.block()}", InsightDrafts,
                       prompt_version=writer.ref, ctx=ctx, step="insight_writer")

    # ---- FACT CHECK: a number that is not in the cited facts = refused ------------------------
    accepted = []
    for d in drafts.insights[:MAX_INSIGHTS]:
        reason = check_draft(d, facts)
        if reason:
            ctx.log("insight_refused", reason, rule_version=writer.ref, evidence={"text": d.text, "facts": d.facts})
        else:
            accepted.append(Insight(text=d.text, evidence={f: facts.items[f] for f in d.facts}))
    return accepted


def write_insights(ctx, con, q: CompiledQuery, request, catalog, manifest, receipts, totals,
                   df: pd.DataFrame) -> list[Insight]:
    """Insights for analysis_result.json: from the LLM agent if possible, else deterministic."""
    reason = "disabled (params llm=false)"
    if ctx.params.get("llm", True):
        try:
            insights = _agent(ctx, con, q, request, catalog, manifest, receipts, totals)
            if insights:
                ctx.log("insights_written", f"{len(insights)} insights from the LLM agent",
                        evidence={"source": "llm", "texts": [i.text for i in insights]})
                return insights
            reason = "every insight was refused by the fact check"
        except (LLMUnavailable, ValidationError) as e:
            reason = f"{type(e).__name__}: {e}"
    insights = compute_insights(df, request.dimensions, q.kpi.unit)
    ctx.log("insights_written", f"{len(insights)} deterministic insights (LLM not used: {reason[:200]})",
            evidence={"source": "fallback", "texts": [i.text for i in insights]})
    return insights
