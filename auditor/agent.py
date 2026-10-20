"""BI Auditor / XAI agent: the last step of the DAG. run(ctx) is called by the orchestrator.

It writes the three outputs fixed by the contracts:
  explanations.json      SHAP explanation of every anomaly decision (step 2)
  integrity_report.json  is the audit journal intact? (hash chain)
  drift_report.json      drift against reference runs (params["drift_reference"]: run ids);
                         without reference runs: an explicit "not_available" report
The interactive "why?" agent (auditor/why.py) is called by the API, not here.

Status: FAILED if the journal was tampered with (nothing can be trusted any more),
NEEDS_REVIEW if drift was detected (a human must look), otherwise SUCCESS.
"""
from auditor.drift.monitor import journal_alerts, monitor_runs
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

    # 3. Drift against reference runs (at least 3). Never a fake result.
    reference = ctx.params.get("drift_reference") or []
    if len(reference) >= 3:
        runs_root = ctx.output_dir.parent.parent                  # runs/<run_id>/auditor -> runs/
        drift = monitor_runs(reference, [ctx.run_id], runs_root=runs_root, write=False)[ctx.run_id]
        journal_alerts(drift, ctx.journal)
    else:
        drift = DriftReport(reference_runs=list(reference), current_run=ctx.run_id, status="not_available",
                            narrative="Drift monitoring needs at least 3 reference runs "
                                      "(params['drift_reference']); not computed.")
    outputs["drift"] = save(drift, ctx.output("drift"))

    if not integrity.ok:
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED,
                           outputs=outputs, message=f"Audit journal tampered: {integrity.problem}")
    drifted = drift.status not in ("stable", "not_available")
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, outputs=outputs,
                       status=AgentStatus.NEEDS_REVIEW if drifted else AgentStatus.SUCCESS,
                       message=f"{n_anom} anomalies explained; journal intact "
                               f"({integrity.entries_checked} entries); drift: {drift.status}.")


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
