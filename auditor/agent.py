"""BI Auditor / XAI agent: the last step of the DAG. run(ctx) is called by the orchestrator.

It writes the three outputs fixed by the contracts:
  explanations.json      SHAP explanation of every anomaly decision (step 2)
  integrity_report.json  is the audit journal intact? (hash chain)
  drift_report.json      placeholder until drift monitoring exists (step 5)
The interactive "why?" agent (auditor/why.py) is called by the API, not here.

Status: FAILED if the journal was tampered with (nothing can be trusted any more),
otherwise SUCCESS.
"""
from auditor.xai.explain import build_report
from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.audit import last_hash, verify_journal
from contracts.common import save
from contracts.xai import DriftReport


def run(ctx: RunContext) -> AgentResult:
    outputs = {}

    # 1. Explanations: copy the decisions, explain them, never change them
    report = build_report(ctx.inputs["anomalies"], ctx.inputs["model"], ctx.inputs["scores"],
                          n_normal=ctx.params.get("n_normal", 20))
    outputs["explanations"] = save(report, ctx.output("explanations"))
    n_anom = sum(e.is_anomaly for e in report.explanations)
    top = report.explanations[0] if report.explanations else None
    ctx.log("explain_anomalies", f"explained {len(report.explanations)} rows ({n_anom} anomalies)",
            rule_version=report.model_version, inputs=[str(ctx.inputs["scores"])],
            outputs=[str(outputs["explanations"])],
            evidence={"explainer": report.explainer, "score_reproduced": "gap < 1e-6",
                      "most_anomalous": top.row_key if top else None,
                      "most_anomalous_narrative": top.narrative if top else None})

    # 2. Integrity of the shared journal
    integrity = verify_journal(ctx.journal)
    outputs["integrity"] = save(integrity, ctx.output("integrity"))
    ctx.log("verify_journal", "INTACT" if integrity.ok else "TAMPERED",
            outputs=[str(outputs["integrity"])],
            evidence={"entries_checked": integrity.entries_checked,
                      "first_bad_entry": integrity.first_bad_entry, "anchor": last_hash(ctx.journal)})

    # 3. Drift: needs several runs (step 5). Explicit placeholder, never a fake result.
    drift = DriftReport(reference_runs=[], current_run=ctx.run_id, status="not_available",
                        narrative="Drift monitoring needs several runs; not computed yet.")
    outputs["drift"] = save(drift, ctx.output("drift"))

    if not integrity.ok:
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED,
                           outputs=outputs, message=f"Audit journal tampered: {integrity.problem}")
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS, outputs=outputs,
                       message=f"{n_anom} anomalies explained; journal intact "
                               f"({integrity.entries_checked} entries).")


if __name__ == "__main__":      # python -m auditor.agent
    import argparse
    from pathlib import Path

    from contracts.audit import DEFAULT_JOURNAL
    from contracts.pipeline import context_for
    a = argparse.ArgumentParser()
    a.add_argument("--run", default="run_001")
    a.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    args = a.parse_args()
    res = run(context_for("auditor", args.run, journal=args.journal))
    print(f"{res.status.value}: {res.message}")
    for k, v in res.outputs.items():
        print(f"  {k}: {v}")
