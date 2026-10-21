"""BO4-12 agent: is this comparison honest? If not, propose a justified adjustment.

    run(ctx)                                  called by the orchestrator
    record_decision(run_id, "accepted", ...)  called by the app when Sarra answers

    python -m comparisons.checker                  # run_001, with Ollama if available
    python -m comparisons.checker --no-llm         # template summary only
    python -m comparisons.checker --accept same_days

Responsibilities (BO4-12 definition):  DQ measures completeness (coverage profile),
SEM supplies definitions (catalog), this step (ANA) assesses comparability.
"""
import argparse

from comparisons.checks import check_coverage, check_grain, check_population, check_scale, check_unit
from comparisons.data import load_inputs
from comparisons.fix import propose_fixes
from comparisons.narrate import summarize, template_parts
from comparisons.rules import RULES_VERSION, Rules
from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import load, save
from contracts.comparisons import CheckStatus, ComparisonReport, FixMethod, UserDecision
from contracts.i18n import Msg, lang_code, render
from contracts.llm import LLMConfig
from contracts.pipeline import context_for


def run(ctx: RunContext) -> AgentResult:
    inp = load_inputs(ctx.inputs)
    req = inp.request
    out_path = ctx.output("report")

    if req.compare_to is None:
        none = [Msg(key="summary.none")]
        report = ComparisonReport(has_comparison=False, rules_version=RULES_VERSION,
                                  summary=render(none), summary_parts=none)
        save(report, out_path)
        ctx.log("comparison_detected", "SKIPPED: no compare_to in the request",
                inputs=[str(ctx.inputs["request"])], outputs=[str(out_path)])
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SKIPPED,
                           outputs={"report": out_path}, message="No comparison requested.")

    rules = Rules(**ctx.params.get("rules", {}))
    as_asked = (inp.kpi_value(req.period), inp.kpi_value(req.compare_to))
    ctx.log("values_as_asked", "computed in SQL", rule_version=f"kpi:{inp.kpi.ref}",
            inputs=[str(ctx.inputs["warehouse"])],
            evidence={"current": as_asked[0], "previous": as_asked[1],
                      "period": req.period.model_dump(), "compare_to": req.compare_to.model_dump()})

    coverage, edges = check_coverage(inp, rules, as_asked)
    scale = check_scale(inp, rules)
    checks = [coverage, check_population(inp, rules), check_unit(inp), scale, check_grain(inp)]
    for c in checks:
        ctx.log(f"check_{c.kind.value}", c.status.value.upper(), rule_version=RULES_VERSION,
                inputs=[str(ctx.inputs["coverage"]), str(ctx.inputs["catalog"])], evidence=c.evidence)

    rec, alts = propose_fixes(inp, coverage, edges, scale)
    for f in ([rec] if rec else []) + alts:
        ctx.log("propose_fix", f"{f.method.value}: {f.description}", rule_version=RULES_VERSION,
                evidence=f.model_dump(mode="json"))

    parts = template_parts(req, checks, as_asked, inp.kpi.unit, rec, alts)
    lang = lang_code(ctx.params.get("language", "fr"))          # language of the LLM summary
    summary, source = summarize(render(parts), checks, ([rec] if rec else []) + alts, ctx=ctx,
                                use_llm=ctx.params.get("llm", True), language=lang,
                                config=LLMConfig(**ctx.params.get("llm_config", {})))

    report = ComparisonReport(has_comparison=True, rules_version=RULES_VERSION, checks=checks,
                              proposed_fix=rec, alternatives=alts, summary=summary,
                              summary_source=source, summary_parts=parts,
                              summary_lang=lang if source.startswith("llm:") else None)
    save(report, out_path)

    blocking = [c.kind.value for c in checks if c.status == CheckStatus.BLOCKING]
    status = AgentStatus.NEEDS_REVIEW if blocking else AgentStatus.SUCCESS
    message = (f"Blocking: {', '.join(blocking)}. " + ("Fix proposed, waiting for the user."
                                                        if rec else "No valid fix: do not show.")
               if blocking else "Comparison is valid." if not rec else "Valid, optional adjustment offered.")
    ctx.log("comparison_verdict", status.value, outputs=[str(out_path)],
            evidence={"blocking": blocking, "fix": rec.method.value if rec else None})
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=status,
                       outputs={"report": out_path}, message=message)


def record_decision(run_id: str, decision: UserDecision | str,
                    chosen_fix: FixMethod | str | None = None, **ctx_kwargs) -> ComparisonReport:
    """The app calls this when Sarra accepts or refuses. Logged in the journal."""
    ctx = context_for("comparisons", run_id, **ctx_kwargs)
    path = ctx.output("report")
    report = load(ComparisonReport, path)
    decision = UserDecision(decision)
    offered = {f.method for f in ([report.proposed_fix] if report.proposed_fix else []) + report.alternatives}
    chosen = FixMethod(chosen_fix) if chosen_fix else None
    if decision == UserDecision.ACCEPTED:
        chosen = chosen or (report.proposed_fix.method if report.proposed_fix else None)
        if chosen not in offered:
            raise ValueError(f"'{chosen}' was not offered. Offered: {[m.value for m in offered]}")
    else:
        chosen = None
    report = report.model_copy(update={"user_decision": decision, "chosen_fix": chosen})
    save(report, path)
    ctx.log("user_decision", f"{decision.value}" + (f": {chosen.value}" if chosen else ""),
            outputs=[str(path)], evidence={"chosen_fix": chosen.value if chosen else None})
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="run_001")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--language", default="fr", help="fr or en")
    p.add_argument("--accept", choices=[m.value for m in FixMethod])
    p.add_argument("--reject", action="store_true")
    args = p.parse_args()

    if args.accept or args.reject:
        r = record_decision(args.run, "rejected" if args.reject else "accepted", args.accept)
        print(f"Decision recorded: {r.user_decision.value} {r.chosen_fix.value if r.chosen_fix else ''}")
        return

    ctx = context_for("comparisons", args.run,
                      params={"llm": not args.no_llm, "language": args.language})
    result = run(ctx)
    report = load(ComparisonReport, result.outputs["report"])
    print(f"Status: {result.status.value} | {result.message}\n")
    for c in report.checks:
        print(f"  [{c.status.value:>8}] {c.kind.value:<10} {c.message}")
    if report.proposed_fix:
        f = report.proposed_fix
        print(f"\nRecommended ({f.method.value}): {f.value_current:,.2f} vs {f.value_previous:,.2f} "
              f"{f.unit} ({f.change_pct:+.1%})")
    for a in report.alternatives:
        print(f"Alternative ({a.method.value}): {a.value_current:,.2f} vs {a.value_previous:,.2f} "
              f"{a.unit} ({a.change_pct:+.1%})")
    print(f"\nSummary for the user [{report.summary_source}]:\n  {report.summary}")


if __name__ == "__main__":
    main()
