"""test_pipeline_e2e.py -- End-to-end tests for the BIFlow pipeline execution.

Covers:
  - Real execution: proves dashboard_spec.json is NOT produced when external modules are absent.
  - Stubbed execution: proves full pipeline completes and generates dashboard_spec.json
    when upstream contracts are satisfied.
"""
from __future__ import annotations

import shutil
import sys
import types
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.analysis import AnalysisResult, ValidationCheck
from contracts.common import save
from contracts.comparisons import ComparisonReport
from contracts.dashboard import DashboardSpec
from contracts.pipeline import output_path
from orchestrator.dag_runner import run_pipeline


def test_real_pipeline_fails_at_dashboard_when_analysis_absent(tmp_path):
    """Proves that with real agents, dashboard fails and does NOT produce dashboard_spec.json."""
    run_id = f"test_real_{uuid.uuid4().hex[:6]}"
    runs_root = tmp_path / "runs"
    db_path = tmp_path / f"tasks_{run_id}.db"
    journal = tmp_path / f"journal_{run_id}.jsonl"

    params = {
        "source_dir": str(REPO_ROOT / "data" / "sample"),
        "question": "Revenue by state in August",
    }

    results = run_pipeline(
        run_id=run_id,
        runs_root=runs_root,
        journal=journal,
        db=db_path,
        params=params,
        stop_on_failure=False,
    )

    # Malek & Samar initial agents succeed
    assert results["upload"].status == AgentStatus.SUCCESS
    assert results["similarity"].status == AgentStatus.SUCCESS
    assert results["column_types"].status == AgentStatus.SUCCESS
    assert results["request"].status == AgentStatus.SUCCESS

    # External agents skipped
    assert results["analysis"].status == AgentStatus.SKIPPED
    assert results["comparisons"].status == AgentStatus.SKIPPED

    # Dashboard fails because analysis.result file does not exist
    assert results["dashboard"].status == AgentStatus.FAILED
    spec_path = output_path(run_id, "dashboard", "spec", runs_root=runs_root)
    assert not spec_path.exists(), "dashboard_spec.json must NOT exist when inputs are absent"


def test_stubbed_pipeline_produces_dashboard_spec(tmp_path):
    """Proves that when upstream contracts are satisfied, dashboard produces dashboard_spec.json."""
    run_id = f"test_stub_{uuid.uuid4().hex[:6]}"
    runs_root = tmp_path / "runs"
    db_path = tmp_path / f"tasks_{run_id}.db"
    journal = tmp_path / f"journal_{run_id}.jsonl"

    def make_stub(name, fn):
        mod = types.ModuleType(name)
        mod.run = fn
        sys.modules[name] = mod

    def stub_pii(ctx: RunContext) -> AgentResult:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        out_rep = ctx.output("report")
        out_rep.write_text("{}", encoding="utf-8")
        tables_out = ctx.output_dir / "tables"
        tables_out.mkdir(parents=True, exist_ok=True)
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                           outputs={"report": out_rep, "tables": tables_out})

    def stub_profiling(ctx: RunContext) -> AgentResult:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        for key in ["profile", "coverage", "anomalies", "model", "scores"]:
            p = ctx.output(key)
            p.write_text("{}", encoding="utf-8")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS)

    def stub_cleaning(ctx: RunContext) -> AgentResult:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        ctx.output("report").write_text("{}", encoding="utf-8")
        (ctx.output_dir / "tables").mkdir(parents=True, exist_ok=True)
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS)

    def stub_etl(ctx: RunContext) -> AgentResult:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        for key in ["warehouse", "manifest", "receipts"]:
            ctx.output(key).write_text("{}", encoding="utf-8")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS)

    def stub_analysis(ctx: RunContext) -> AgentResult:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        from contracts.semantic import AnalysisRequest
        from contracts.common import load
        req = load(AnalysisRequest, ctx.inputs["request"])
        result = AnalysisResult(
            request=req,
            kpi=f"{req.metric}@2.0",
            sql="SELECT customer_state, SUM(payment_value) FROM fact_payments GROUP BY 1",
            rows=5,
            value_current=5000.0,
            unit="BRL",
            validations=[ValidationCheck(name="valid", passed=True, detail="ok")],
        )
        res_p = ctx.output("result")
        save(result, res_p)
        ctx.output("data").write_text("", encoding="utf-8")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                           outputs={"result": res_p, "data": ctx.output("data")})

    def stub_comparisons(ctx: RunContext) -> AgentResult:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        comp = ComparisonReport(has_comparison=False, checks=[])
        out_p = ctx.output("report")
        save(comp, out_p)
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                           outputs={"report": out_p})

    def stub_noop(ctx: RunContext) -> AgentResult:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        for key in STEPS[ctx.agent].outputs:
            ctx.output(key).write_text("{}", encoding="utf-8")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS)

    make_stub("privacy.pii", stub_pii)
    make_stub("profiling.profiler", stub_profiling)
    make_stub("cleaning.cleaner", stub_cleaning)
    make_stub("etl.build", stub_etl)
    make_stub("analysis.analyst", stub_analysis)
    make_stub("comparisons.checker", stub_comparisons)
    make_stub("etl.lineage", stub_noop)
    make_stub("auditor.agent", stub_noop)

    params = {
        "source_dir": str(REPO_ROOT / "data" / "sample"),
        "question": "Revenue by state in August",
    }

    results = run_pipeline(
        run_id=run_id,
        runs_root=runs_root,
        journal=journal,
        db=db_path,
        params=params,
        stop_on_failure=True,
    )

    assert results["dashboard"].status == AgentStatus.SUCCESS
    spec_path = output_path(run_id, "dashboard", "spec", runs_root=runs_root)
    assert spec_path.exists()
    spec = DashboardSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    assert spec.kpi == "Revenue@2.0"
    assert len(spec.charts) == 2
