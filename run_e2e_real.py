"""run_e2e_real.py -- Run the pipeline E2E with real agents on data/sample.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.pipeline import STEPS, output_path
from orchestrator.dag_runner import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

RUN_ID = "run_audit_real_001"
RUNS_DIR = REPO_ROOT / "runs" / RUN_ID
DB_PATH = REPO_ROOT / f"task_store_{RUN_ID}.db"
JOURNAL_PATH = REPO_ROOT / f"audit_journal_{RUN_ID}.jsonl"

# Clean previous run if exists
if RUNS_DIR.exists():
    shutil.rmtree(RUNS_DIR)
if DB_PATH.exists():
    DB_PATH.unlink()
if JOURNAL_PATH.exists():
    JOURNAL_PATH.unlink()

print("=" * 80)
print(f"PIPELINE RUN: {RUN_ID} (REAL AGENTS)")
print("=" * 80)

params = {
    "source_dir": str(REPO_ROOT / "data" / "sample"),
    "question": "Revenue by state in August",
    "uploaded_by": "AuditTester",
}

results = run_pipeline(
    run_id=RUN_ID,
    runs_root=REPO_ROOT / "runs",
    journal=JOURNAL_PATH,
    db=DB_PATH,
    params=params,
    stop_on_failure=False,  # Let DAG proceed as far as possible
)

print("\n" + "=" * 80)
print("E2E PIPELINE EXECUTION SUMMARY (REAL AGENTS)")
print("=" * 80)

for step_name, step_def in STEPS.items():
    res = results.get(step_name)
    status_str = res.status.value if res else "NOT_RUN"
    msg = res.message if res else ""
    
    # Check expected outputs
    artifacts = {}
    for out_key, out_filename in step_def.outputs.items():
        p = output_path(RUN_ID, step_name, out_key, runs_root=REPO_ROOT / "runs")
        artifacts[out_key] = {
            "path": str(p.relative_to(REPO_ROOT)),
            "exists": p.exists(),
            "size": p.stat().st_size if p.exists() else 0,
        }

    print(f"\nStep: {step_name.upper()} (Owner: {step_def.owner})")
    print(f"  Entrypoint : {step_def.entrypoint}")
    print(f"  Status     : {status_str}")
    print(f"  Message    : {msg}")
    print(f"  Inputs     : {step_def.inputs}")
    print(f"  Artifacts  : {artifacts}")

print("\n" + "=" * 80)
dashboard_spec_path = output_path(RUN_ID, "dashboard", "spec", runs_root=REPO_ROOT / "runs")
print(f"DASHBOARD SPEC CHECK: {dashboard_spec_path} -> Exists = {dashboard_spec_path.exists()}")
print("=" * 80)
