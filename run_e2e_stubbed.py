"""run_e2e_stubbed.py -- Run the full pipeline with real agents + stubs for missing external agents.

Verifies end-to-end data flow into dashboard when all contracts are satisfied.
"""
from __future__ import annotations

import logging
import shutil
import sys
import types
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.analysis import AnalysisResult, ValidationCheck
from contracts.common import Period, save
from contracts.comparisons import ComparisonReport
from contracts.pipeline import STEPS, output_path
from orchestrator.dag_runner import run_pipeline

RUN_ID = "run_audit_stubbed_002"
RUNS_DIR = REPO_ROOT / "runs" / RUN_ID
DB_PATH = REPO_ROOT / f"task_store_{RUN_ID}.db"
JOURNAL_PATH = REPO_ROOT / f"audit_journal_{RUN_ID}.jsonl"

if RUNS_DIR.exists():
    shutil.rmtree(RUNS_DIR)
if DB_PATH.exists():
    DB_PATH.unlink()
if JOURNAL_PATH.exists():
    JOURNAL_PATH.unlink()

def make_stub_module(name: str, run_fn):
    mod = types.ModuleType(name)
    mod.run = run_fn
    sys.modules[name] = mod
    return mod

def _populate_mock_outputs(ctx: RunContext):
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    import shutil
    ex_dir = REPO_ROOT / "contracts" / "examples" / "run_001" / ctx.agent
    for key, fname in STEPS[ctx.agent].outputs.items():
        out_p = ctx.output(key)
        if fname.endswith("/"):
            out_p.mkdir(parents=True, exist_ok=True)
        elif fname.endswith(".parquet"):
            pd.DataFrame([{"dummy": 1.0}]).to_parquet(out_p)
        elif fname.endswith(".duckdb"):
            import duckdb
            con = duckdb.connect(str(out_p))
            con.execute("CREATE TABLE dummy (x INT)")
            con.close()
        elif fname.endswith(".joblib"):
            import joblib
            joblib.dump({"dummy": 1}, out_p)
        else:
            ex_file = ex_dir / fname
            if ex_file.exists():
                shutil.copy2(ex_file, out_p)
            else:
                out_p.write_text('{"status": "ok"}', encoding="utf-8")

def stub_pii(ctx: RunContext) -> AgentResult:
    _populate_mock_outputs(ctx)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       outputs={"report": ctx.output("report"), "tables": ctx.output_dir / "tables"},
                       message="PII stub: pass-through")

def stub_profiling(ctx: RunContext) -> AgentResult:
    _populate_mock_outputs(ctx)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       message="Profiling stub: pass-through")

def stub_cleaning(ctx: RunContext) -> AgentResult:
    _populate_mock_outputs(ctx)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       message="Cleaning stub: pass-through")

def stub_etl(ctx: RunContext) -> AgentResult:
    _populate_mock_outputs(ctx)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       message="ETL stub: pass-through")

def stub_analysis(ctx: RunContext) -> AgentResult:
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    from contracts.semantic import AnalysisRequest
    from contracts.common import load
    req = load(AnalysisRequest, ctx.inputs["request"])
    
    result = AnalysisResult(
        request=req,
        kpi=f"{req.metric}@2.0",
        sql="SELECT customer_state, SUM(payment_value) FROM fact_payments GROUP BY 1",
        rows=10,
        value_current=12345.67,
        unit="BRL",
        validations=[ValidationCheck(name="grain", passed=True, detail="ok")],
    )
    res_path = ctx.output("result")
    save(result, res_path)
    import pandas as pd
    data_path = ctx.output("data")
    pd.DataFrame([{"customer_state": "SP", "Revenue": 12345.67}]).to_parquet(data_path)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       outputs={"result": res_path, "data": data_path}, message="Analysis stub: generated AnalysisResult")

def stub_comparisons(ctx: RunContext) -> AgentResult:
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    comp = ComparisonReport(has_comparison=False, checks=[])
    out_p = ctx.output("report")
    save(comp, out_p)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       outputs={"report": out_p}, message="Comparisons stub: generated ComparisonReport")

def stub_lineage(ctx: RunContext) -> AgentResult:
    _populate_mock_outputs(ctx)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       outputs={"graph": ctx.output("graph")}, message="Lineage stub")

def stub_auditor(ctx: RunContext) -> AgentResult:
    _populate_mock_outputs(ctx)
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                       outputs={"explanations": ctx.output("explanations"),
                                "drift": ctx.output("drift"),
                                "integrity": ctx.output("integrity")}, message="Auditor stub")

# Inject stubs
make_stub_module("privacy.pii", stub_pii)
make_stub_module("profiling.profiler", stub_profiling)
make_stub_module("cleaning.cleaner", stub_cleaning)
make_stub_module("etl.build", stub_etl)
make_stub_module("analysis.analyst", stub_analysis)
make_stub_module("comparisons.checker", stub_comparisons)
make_stub_module("etl.lineage", stub_lineage)
make_stub_module("auditor.agent", stub_auditor)

params = {
    "source_dir": str(REPO_ROOT / "data" / "sample"),
    "question": "Revenue by state in August",
    "uploaded_by": "AuditTester",
}

print("=" * 80)
print(f"PIPELINE RUN: {RUN_ID} (WITH SIMULATED/STUBBED AGENTS)")
print("=" * 80)

results = run_pipeline(
    run_id=RUN_ID,
    runs_root=REPO_ROOT / "runs",
    journal=JOURNAL_PATH,
    db=DB_PATH,
    params=params,
    stop_on_failure=True,
)

print("\n" + "=" * 80)
print("E2E PIPELINE EXECUTION SUMMARY (WITH STUBBED AGENTS)")
print("=" * 80)

for step_name, step_def in STEPS.items():
    res = results.get(step_name)
    status_str = res.status.value if res else "NOT_RUN"
    msg = res.message if res else ""
    
    artifacts = {}
    for out_key, out_filename in step_def.outputs.items():
        p = output_path(RUN_ID, step_name, out_key, runs_root=REPO_ROOT / "runs")
        artifacts[out_key] = {
            "path": str(p.relative_to(REPO_ROOT)),
            "exists": p.exists(),
            "size": p.stat().st_size if p.exists() else 0,
        }

    print(f"\nStep: {step_name.upper()} (Owner: {step_def.owner})")
    print(f"  Status     : {status_str}")
    print(f"  Message    : {msg}")
    print(f"  Artifacts  : {artifacts}")

print("\n" + "=" * 80)
dashboard_spec_path = output_path(RUN_ID, "dashboard", "spec", runs_root=REPO_ROOT / "runs")
print(f"DASHBOARD SPEC CHECK: {dashboard_spec_path} -> Exists = {dashboard_spec_path.exists()}")
if dashboard_spec_path.exists():
    from contracts.dashboard import DashboardSpec
    spec = DashboardSpec.model_validate_json(dashboard_spec_path.read_text(encoding="utf-8"))
    print(f"DashboardSpec Title   : {spec.title}")
    print(f"DashboardSpec KPI     : {spec.kpi}")
    print(f"DashboardSpec Charts  : {len(spec.charts)} ({[c.chart_type.value for c in spec.charts]})")
    print(f"DashboardSpec Warnings: {spec.warnings}")
print("=" * 80)
