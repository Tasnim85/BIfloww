"""Run one agent at a time for interactive integration tests."""
import importlib
import json
import re
from pathlib import Path

from contracts.agent import RunContext

STEPS = {
    "pii": "privacy.agent",
    "profiling": "profiling.agent",
    "cleaning": "cleaning.agent",
    "etl": "etl.agent",
    "lineage": "etl.lineage",
}


def run_step(name: str, dataset: Path, runs: Path, run_id: str, *, schema_mode="llm", backend="neo4j", pii_uncertain="review", proposal=None, approval=None, playbook=None):
    if name not in STEPS:
        raise ValueError("Unknown task")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", run_id):
        raise ValueError("run_id must be a single safe directory name")
    root = runs / run_id
    destination = root / name
    if destination.exists():
        saved_result = destination / "agent_result.json"
        pending = json.loads(saved_result.read_text(encoding="utf-8")) if saved_result.exists() else {}
        if name != "cleaning" or not proposal or not approval or pending.get("status") != "needs_review" or (destination / "tables").exists():
            raise FileExistsError("This task already has an output directory; choose a fresh run_id")
    inputs = {
        "pii": {"tables": dataset},
        "profiling": {"tables": root / "pii/tables"},
        "cleaning": {"tables": root / "pii/tables", "profile": root / "profiling/profile_report.json"},
        "etl": {"tables": root / "cleaning/tables", "cleaning_report": root / "cleaning/cleaning_report.json"},
        "lineage": {"receipts": root / "etl/receipts.json", "manifest": root / "etl/warehouse_manifest.json"},
    }[name]
    if name == "cleaning" and not inputs["profile"].exists():
        del inputs["profile"]
    if name == "cleaning":
        if proposal:
            inputs["proposal"] = Path(proposal)
        if approval:
            inputs["approval"] = Path(approval)
    elif proposal or approval or playbook:
        raise ValueError("Cleaning options require the cleaning task")
    for path in inputs.values():
        if not path.exists():
            raise FileNotFoundError(f"Missing input; run the upstream task first: {path}")
    params = {"schema_mode": schema_mode} if name == "etl" else {"backend": backend} if name == "lineage" else {"uncertain_policy": pii_uncertain, "show_progress": True} if name == "pii" else {}
    if name == "cleaning" and playbook:
        params["playbook"] = str(playbook)
    result = importlib.import_module(STEPS[name]).run(RunContext(run_id=run_id, agent=name, inputs=inputs, output_dir=destination, params=params))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "agent_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
