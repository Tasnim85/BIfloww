"""DriftMonitor (the Auditor in supervision mode): does a run still behave like the
reference runs? Read-only on the agents. It NEVER reads the planted truth of a simulation.

Decision rules (fixed, versioned, written in plain language):
  data drift       = at least one input variable with PSI > 0.25
  decision drift   = at least one output metric outside its control limits
  reasoning drift  = a shap_share_* metric outside its limits (the model weighs its
                     features differently)
Diagnosis:
  data + decisions            -> data_drift      decisions follow the data
  data only                   -> data_drift_only the model may no longer fit the data
  decisions only, reasoning OK-> agent_changed   same reasoning, so a SETTING changed
                                                 (threshold, filter, a lost step...)
  decisions + reasoning only  -> agent_changed   the MODEL itself changed
  nothing                     -> stable
Always "a diagnosis, not a proof: a human decides".

    python -m auditor.drift.monitor      # runs the simulated months (see auditor/dev/simulate_runs.py)
"""
import argparse
import json
from pathlib import Path

import numpy as np

from auditor.drift import stats
from auditor.drift.observe import Observation, observe_run
from contracts.audit import DEFAULT_JOURNAL, AuditEvent, log_event
from contracts.common import save
from contracts.pipeline import RUNS_ROOT, output_path
from contracts.xai import DriftReport, InputDriftCheck, MetricDriftCheck

RULES_VERSION = "drift-rules@1.0"


class DriftMonitor:
    def __init__(self, reference: list[Observation]):
        if len(reference) < 3:
            raise ValueError("drift needs at least 3 reference runs to estimate normal variation")
        self.reference_runs = [o.run_id for o in reference]
        keys_in = set.intersection(*(set(o.inputs) for o in reference))
        keys_out = set.intersection(*(set(o.metrics) for o in reference))
        self.ref_inputs = {k: np.concatenate([o.inputs[k] for o in reference]) for k in keys_in}
        self.limits = {}
        for k in keys_out:
            values = [o.metrics[k].value for o in reference]
            self.limits[k] = stats.control_limits(values, min_rel_sigma=reference[0].metrics[k].min_rel_sigma)

    def check(self, obs: Observation) -> DriftReport:
        inputs, metrics = [], []
        for (agent, name), ref in sorted(self.ref_inputs.items()):
            if (agent, name) in obs.inputs:
                cur = obs.inputs[(agent, name)]
                p = stats.psi(ref, cur)
                _, pv = stats.ks_test(ref, cur)
                inputs.append(InputDriftCheck(agent=agent, name=name, psi=round(p, 4),
                                              ks_pvalue=float(pv), flagged=p > stats.PSI_DRIFT))
        for (agent, name), (center, lo, hi) in sorted(self.limits.items()):
            if (agent, name) in obs.metrics:
                v = obs.metrics[(agent, name)].value
                metrics.append(MetricDriftCheck(agent=agent, name=name, value=round(v, 6),
                                                center=round(center, 6), lower=round(lo, 6),
                                                upper=round(hi, 6), out_of_control=not lo <= v <= hi))
        return self._diagnose(obs.run_id, inputs, metrics)

    def _diagnose(self, run_id: str, inputs: list, metrics: list) -> DriftReport:
        data = [c for c in inputs if c.flagged]
        out = [c for c in metrics if c.out_of_control]
        reasoning = [c for c in out if c.name.startswith("shap_share_")]
        decisions = [c for c in out if not c.name.startswith("shap_share_")]
        agents = sorted({c.agent for c in out})
        d_txt = ", ".join(f"{c.agent}.{c.name} (PSI {c.psi:.2f})" for c in data)
        o_txt = ", ".join(f"{c.agent}.{c.name} = {c.value:.4f} (limits {c.lower:.4f} to {c.upper:.4f})"
                          for c in out)

        if data and out:
            status = "data_drift"
            text = (f"{run_id}: the input data changed ({d_txt}) and the outputs changed too ({o_txt}). "
                    f"The decisions most likely follow the data. Check that this change is legitimate.")
        elif data:
            status = "data_drift_only"
            text = (f"{run_id}: the input data changed ({d_txt}) but no output left its limits. "
                    f"The models may no longer fit the data: keep watching.")
        elif decisions and not reasoning:
            status = "agent_changed"
            explained = sorted({c.agent for c in metrics if c.name.startswith("shap_share_")} & set(agents))
            why = (f" The explanations of {', '.join(explained)} show the same reasoning as usual, so a "
                   f"SETTING changed (for example a threshold), not the model itself." if explained else
                   " A setting, a filter or a processing step probably changed.")
            text = (f"{run_id}: the input data is stable, yet the behaviour of {', '.join(agents)} "
                    f"changed ({o_txt}).{why}")
        elif out:
            status = "agent_changed"
            text = (f"{run_id}: the input data is stable, yet the model weighs its features differently "
                    f"({o_txt}). The model itself was probably changed or retrained.")
        else:
            status = "stable"
            text = f"{run_id}: inputs and outputs are within the reference limits."
        return DriftReport(reference_runs=self.reference_runs, current_run=run_id, status=status,
                           input_checks=inputs, metric_checks=metrics, flagged_agents=agents,
                           narrative=text + " This is a diagnosis, not a proof: a human decides.")


def journal_alerts(report: DriftReport, journal: Path) -> None:
    """D1 data drift, D2 decision drift, D3 diagnosis: one entry each, under the run's id."""
    def log(step, decision, evidence):
        log_event(AuditEvent(run_id=report.current_run, agent="auditor", step=step, decision=decision,
                             rule_version=RULES_VERSION, evidence=evidence), journal)
    for c in report.input_checks:
        if c.flagged:
            log("D1_data_drift", f"{c.agent}.{c.name}: PSI {c.psi:.3f} > {stats.PSI_DRIFT}",
                c.model_dump() | {"reference_runs": report.reference_runs})
    for c in report.metric_checks:
        if c.out_of_control:
            log("D2_decision_drift", f"{c.agent}.{c.name} = {c.value:.4f} outside [{c.lower:.4f}, {c.upper:.4f}]",
                c.model_dump() | {"reference_runs": report.reference_runs})
    log("D3_diagnosis", report.status, {"flagged_agents": report.flagged_agents,
                                        "narrative": report.narrative})


def monitor_runs(reference: list[str], runs: list[str], runs_root: Path = RUNS_ROOT,
                 journal: Path = DEFAULT_JOURNAL, write: bool = True) -> dict[str, DriftReport]:
    monitor = DriftMonitor([observe_run(r, runs_root) for r in reference])
    reports = {}
    for run in runs:
        report = monitor.check(observe_run(run, runs_root))
        reports[run] = report
        if write:
            save(report, output_path(run, "auditor", "drift", runs_root))
            journal_alerts(report, journal)
    return reports


def main() -> None:
    from auditor.dev.simulate_runs import DRIFT_JOURNAL, MONITORED, REFERENCE, TRUTH_FILE
    p = argparse.ArgumentParser()
    p.add_argument("--journal", type=Path, default=DRIFT_JOURNAL)
    args = p.parse_args()

    reports = monitor_runs(REFERENCE, MONITORED, journal=args.journal)
    truth = json.loads(TRUTH_FILE.read_text(encoding="utf-8"))      # evaluation only, after the fact
    expected = {"stable": ("stable", []), "agent_changed:profiling": ("agent_changed", ["profiling"]),
                "agent_changed:etl": ("agent_changed", ["etl"]), "data_drift": ("data_drift", None)}
    print(f"Reference runs: {', '.join(REFERENCE)}\n")
    print(f"{'run':<13} {'planted (hidden)':<26} {'detected':<15} {'agents flagged':<16} match")
    for run, r in reports.items():
        want_status, want_agents = expected[truth[run]["label"]]
        ok = r.status == want_status and (want_agents is None or r.flagged_agents == want_agents)
        print(f"{run:<13} {truth[run]['what']:<26} {r.status:<15} {', '.join(r.flagged_agents) or '-':<16} "
              f"{'OK' if ok else 'MISS'}")
    print()
    for run, r in reports.items():
        print(f"- {r.narrative}\n")
    print(f"Alerts written to {args.journal}; reports in runs/<run>/auditor/drift_report.json")


if __name__ == "__main__":
    main()
