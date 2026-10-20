"""The tools of the "why?" agent. READ-ONLY: they never write anything.

Each tool returns plain text built from real files (journal, lineage, reports,
catalog). The LLM only chooses which tool to call and writes the final answer;
every fact it can use comes from these outputs.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from contracts.audit import JournalEntry, read_events
from contracts.common import load
from contracts.pipeline import REPO_ROOT, RUNS_ROOT, output_path
from contracts.registry import CONTRACT_OF

MAX_CHARS = 2500          # a tool answer is cut beyond this (keeps the prompt small)


def _short(value, limit: int = 300) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "..."


def _line(e: JournalEntry) -> str:
    rv = f" [{e.rule_version}]" if e.rule_version else ""
    return f"#{e.entry_id} {e.agent}.{e.step}{rv}: {e.decision} | evidence {_short(e.evidence, 160)}"


@dataclass
class Toolbox:
    run_id: str
    journal: Path
    runs_root: Path = RUNS_ROOT
    repo_root: Path = REPO_ROOT
    calls: list = field(default_factory=list)      # trace of every call (for the audit)

    # ---- catalogue shown to the LLM (names, arguments, purpose) ------------------
    SPEC = {
        "search_journal": ("agent?, step?, text?, limit?",
                           "Find decisions in the audit journal of this run (the run is already "
                           "selected: never pass a run id). agent = a pipeline agent name "
                           "(pii, cleaning, etl, analysis, comparisons, auditor). The journal is in "
                           "ENGLISH: search 'text' with English words (coverage, fix, decision, "
                           "anomal...). Returns one line per entry with its #id; evidence is shortened."),
        "get_entry": ("entry_id", "Full content of one journal entry (all evidence)."),
        "trace_lineage": ("node",
                          "Where a number comes from: upstream path of a lineage node, e.g. "
                          "'kpi:Revenue@2.0' or 'table:fact_payments'. Use node='list' to see all nodes."),
        "kpi_definition": ("name", "Definition of a KPI in the catalog: formula, table, filters, unit, population."),
        "read_report": ("name, row_key?",
                        "Summary of a report of this run, with the #ids of the journal entries "
                        "behind it (cite those). name = comparison | analysis | cleaning | pii | "
                        "drift | anomaly_explanation (without row_key: the most anomalous rows; "
                        "with row_key: the explanation of that row)."),
    }

    def describe(self) -> str:
        return "\n".join(f"- {n}({a}): {d}" for n, (a, d) in self.SPEC.items())

    def schemas(self) -> list[dict]:
        """Native tool-calling specs (name, description, JSON Schema of the arguments)."""
        s, i = {"type": "string"}, {"type": "integer"}
        params = {
            "search_journal": {"properties": {"agent": s, "step": s, "text": s, "limit": i}, "required": []},
            "get_entry": {"properties": {"entry_id": i}, "required": ["entry_id"]},
            "trace_lineage": {"properties": {"node": s}, "required": ["node"]},
            "kpi_definition": {"properties": {"name": s}, "required": ["name"]},
            "read_report": {"properties": {"name": {"type": "string", "enum": [
                "comparison", "analysis", "cleaning", "pii", "drift", "anomaly_explanation"]}, "row_key": s},
                "required": ["name"]},
        }
        specs = [{"name": n, "description": d, "parameters": {"type": "object", **params[n]}}
                 for n, (_, d) in self.SPEC.items()]
        specs.append({"name": "final_answer",
                      "description": "Give the final answer to the manager. Call it once, at the end.",
                      "parameters": {"type": "object", "properties": {
                          "answer": s, "citations": {"type": "array", "items": i}},
                          "required": ["answer", "citations"]}})
        return specs

    def call(self, name: str, args: dict) -> str:
        """Run one tool. Errors are returned as text so the agent can correct itself."""
        fn = getattr(self, f"_t_{name}", None)
        try:
            out = fn(**args) if fn and name in self.SPEC else f"ERROR: unknown tool '{name}'."
        except TypeError as e:
            out = f"ERROR: wrong arguments for {name}: {e}. Expected: {self.SPEC[name][0]}"
        except FileNotFoundError as e:
            out = f"ERROR: not available for this run ({Path(str(e.filename or e)).name})."
        except Exception as e:                                   # never crash the agent
            out = f"ERROR: {type(e).__name__}: {e}"
        out = out if len(out) <= MAX_CHARS else out[:MAX_CHARS] + "\n...(cut)"
        self.calls.append({"tool": name, "args": args, "chars": len(out)})
        return out

    # ---- the tools -----------------------------------------------------------------
    def _events(self) -> list[JournalEntry]:
        return [e for e in read_events(self.journal, run_id=self.run_id)    # LLM bookkeeping and
                if not e.step.startswith("llm:") and e.step != "why_answer"]   # past answers = noise

    def _t_search_journal(self, agent: str = None, step: str = None, text: str = None,
                          limit: int = 12) -> str:
        hits = self._events()
        if agent:
            known = sorted({e.agent for e in hits})
            hits = [e for e in hits if agent.lower() in e.agent.lower()]
            if not hits:
                return f"No entry for agent '{agent}'. Agents in this run: {', '.join(known)}."
        if step:
            hits = [e for e in hits if step.lower() in e.step.lower()]
        if text:
            words = [w for w in text.lower().split() if len(w) > 2]
            hits = [e for e in hits
                    if any(w in f"{e.step} {e.decision} {json.dumps(e.evidence, default=str)}".lower()
                           for w in words)]
        if not hits:
            return "No matching entry. Try search_journal() without filters to see everything."
        shown = hits[:int(limit)]
        more = f"\n({len(hits) - len(shown)} more, refine the search)" if len(hits) > len(shown) else ""
        return "\n".join(_line(e) for e in shown) + more

    def entry_text(self, entry_id: int) -> str:
        """Full text of an entry, for the citation check (not a tool, not traced)."""
        e = next((x for x in read_events(self.journal, run_id=self.run_id) if x.entry_id == int(entry_id)), None)
        return "" if e is None else json.dumps(e.model_dump(mode="json"), ensure_ascii=False, default=str)

    def _t_get_entry(self, entry_id: int) -> str:
        for e in read_events(self.journal, run_id=self.run_id):
            if e.entry_id == int(entry_id):
                return json.dumps(e.model_dump(mode="json", exclude={"prev_hash", "entry_hash"}),
                                  ensure_ascii=False, indent=1, default=str)
        return f"ERROR: no entry #{entry_id} in run {self.run_id}."

    def _t_trace_lineage(self, node: str) -> str:
        graph = load(CONTRACT_OF["lineage.graph"], output_path(self.run_id, "lineage", "graph", self.runs_root))
        labels = {n.id: f"{n.id} ({n.kind.value}: {n.label})" for n in graph.nodes}
        if node == "list":
            return "\n".join(labels.values())
        if node not in labels:
            return f"ERROR: unknown node '{node}'. Known: {', '.join(labels)}"
        lines, frontier, seen = [], [node], set()
        while frontier:                                    # walk upstream, breadth first
            target = frontier.pop(0)
            for e in graph.edges:
                if e.target == target and (e.source, target) not in seen:
                    seen.add((e.source, target))
                    lines.append(f"{labels[target]}  <-[{e.relation}]-  {labels[e.source]}")
                    frontier.append(e.source)
        return "\n".join(lines) or f"{labels[node]} has no upstream node."

    def _t_kpi_definition(self, name: str) -> str:
        from contracts.pipeline import resolve
        from contracts.semantic import KpiCatalog, load_yaml
        catalog = load_yaml(KpiCatalog, resolve("static:kpi/catalog.yaml", self.run_id,
                                                self.runs_root, self.repo_root))
        kpi = next((k for k in catalog.kpis if k.name.lower() == name.lower()), None)
        if kpi is None:
            return f"ERROR: no KPI '{name}'. Known: {', '.join(k.name for k in catalog.kpis)}"
        return json.dumps(kpi.model_dump(), ensure_ascii=False, indent=1) + f"\nref: {kpi.ref}"

    def _related(self, agent: str, steps: tuple = ()) -> str:
        """Journal entries that produced a report, so the agent can cite them."""
        ids = [f"#{e.entry_id} {e.step}" for e in self._events()
               if e.agent == agent and (not steps or e.step in steps)]
        return "\nJournal entries behind this report: " + (", ".join(ids) if ids else "none")

    def _t_read_report(self, name: str, row_key: str = None) -> str:
        text = self._report(name, row_key)
        agent, steps = {"comparison": ("comparisons", ()), "analysis": ("analysis", ()),
                        "cleaning": ("cleaning", ()), "pii": ("pii", ()),
                        "drift": ("auditor", ("D1_data_drift", "D2_decision_drift", "D3_diagnosis")),
                        "anomaly_explanation": ("auditor", ("explain_anomalies",))}.get(name, (None, ()))
        if agent and not text.startswith("ERROR"):
            text += self._related(agent, steps)
        return text

    def _report(self, name: str, row_key: str = None) -> str:
        path = lambda step, key: output_path(self.run_id, step, key, self.runs_root)   # noqa: E731
        if name == "comparison":
            r = load(CONTRACT_OF["comparisons.report"], path("comparisons", "report"))
            fixes = ([r.proposed_fix] if r.proposed_fix else []) + r.alternatives
            return "\n".join(
                [f"rules: {r.rules_version} | user decision: {r.user_decision.value}"
                 + (f" ({r.chosen_fix.value})" if r.chosen_fix else "")]
                + [f"check {c.kind.value} = {c.status.value}: {c.message}" for c in r.checks]
                + [f"{'recommended' if i == 0 else 'alternative'} {f.method.value}: {f.description} "
                   f"-> {f.value_current:,.2f} vs {f.value_previous:,.2f} {f.unit} "
                   f"({f.change_pct:+.1%}). Why: {f.justification}" for i, f in enumerate(fixes)])
        if name == "analysis":
            r = load(CONTRACT_OF["analysis.result"], path("analysis", "result"))
            return "\n".join([f"kpi: {r.kpi} | unit: {r.unit}",
                              f"current: {r.value_current:,.2f} | previous: {r.value_previous or 0:,.2f}",
                              f"sql: {r.sql}"]
                             + [f"validation {v.name}: {'passed' if v.passed else 'FAILED'} - {v.detail}"
                                for v in r.validations]
                             + [f"insight: {i.text}" for i in r.insights])
        if name == "cleaning":
            r = load(CONTRACT_OF["cleaning.report"], path("cleaning", "report"))
            return "\n".join([f"playbook: {r.playbook}"]
                             + [f"rule {a.rule_id} on {a.table}.{a.column}: {a.rows_affected} rows"
                                for a in r.applied])
        if name == "pii":
            r = load(CONTRACT_OF["pii.report"], path("pii", "report"))
            return "\n".join([f"policy: {r.policy_version}"]
                             + [f"{c.table}.{c.column}: {c.pii_kind.value} -> {c.action.value} ({c.method})"
                                for c in r.columns])
        if name == "drift":
            r = load(CONTRACT_OF["auditor.drift"], path("auditor", "drift"))
            out = [c for c in r.metric_checks if c.out_of_control]
            return "\n".join([f"status: {r.status} | reference runs: {', '.join(r.reference_runs) or 'none'}",
                              f"diagnosis: {r.narrative}"]
                             + [f"input {c.agent}.{c.name}: PSI {c.psi:.3f}" + (" (DRIFT)" if c.flagged else "")
                                for c in r.input_checks]
                             + [f"out of limits: {c.agent}.{c.name} = {c.value} (limits {c.lower} to {c.upper})"
                                for c in out])
        if name == "anomaly_explanation":
            r = load(CONTRACT_OF["auditor.explanations"], path("auditor", "explanations"))
            if not row_key:
                top = r.explanations[:5]
                return "Most anomalous rows: " + ", ".join(f"{e.row_key} (score {e.anomaly_score:.3f})" for e in top)
            e = next((x for x in r.explanations if x.row_key == row_key), None)
            if e is None:
                return f"ERROR: row '{row_key}' was not explained in this run."
            return (f"{e.row_key}: anomaly={e.is_anomaly}, score {e.anomaly_score:.3f}. {e.narrative}\n"
                    + "\n".join(f"  {c.feature} = {c.value} -> shap {c.shap_value:+.3f}" for c in e.contributions))
        return (f"ERROR: unknown report '{name}'. "
                f"Use comparison | analysis | cleaning | pii | drift | anomaly_explanation.")
