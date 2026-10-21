"""Sequential BO2 smoke runner, not Samar's DAG orchestrator."""
import importlib
import json
import os
import re
from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext


def run_pipeline(dataset: Path, runs: Path, run_id: str, *, schema_mode: str | None = None, lineage_backend: str | None = None, llm_model: str | None = None, workload: str | None = None) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", run_id):
        raise ValueError("run_id must be a single safe directory name")
    root = runs / run_id
    root.mkdir(parents=True, exist_ok=False)
    results = {}
    steps = [
        ("pii", "privacy.pii", {"tables": dataset}),
        ("profiling", "profiling.profiler", {"tables": root / "pii" / "tables"}),
        ("cleaning", "cleaning.cleaner", {"tables": root / "pii" / "tables", "profile": root / "profiling" / "profile_report.json"}),
        ("etl", "etl.build", {"tables": root / "cleaning" / "tables", "cleaning_report": root / "cleaning" / "cleaning_report.json"}),
        ("lineage", "etl.lineage", {"receipts": root / "etl" / "receipts.json", "manifest": root / "etl" / "warehouse_manifest.json"}),
    ]
    final_status = AgentStatus.SUCCESS
    for name, module, inputs in steps:
        params = {}
        if name == "pii":
            params = {"show_progress": True}
        elif name == "etl":
            params = {"warehouse_mode": "auto", "schema_mode": schema_mode or os.environ.get("BO2_ETL_SCHEMA_MODE", "llm")}
            if llm_model:
                params["llm_model"] = llm_model
            if workload:
                params["workload"] = workload
        elif name == "lineage":
            params = {"backend": lineage_backend or os.environ.get("BO2_LINEAGE_BACKEND", "neo4j")}
        result = importlib.import_module(module).run(RunContext(run_id=run_id, agent=name, inputs=inputs, output_dir=root / name, params=params, journal=runs / "audit_journal.db"))
        result = AgentResult.model_validate(result)
        results[name] = result.model_dump(mode="json")
        print(f"{name}: {result.status.value}" + (f" - {result.message}" if result.message else ""), flush=True)
        if result.status != AgentStatus.SUCCESS:
            final_status = result.status
            break
    summary = {"run_id": run_id, "status": final_status.value, "agents": results}
    (root / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
