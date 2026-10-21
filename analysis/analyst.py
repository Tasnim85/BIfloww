"""Step 5: the Analyst agent (Rabeb). The orchestrator calls  analysis.analyst:run.

It follows the agent model of the contracts README (section 5): READ, WORK, LOG, WRITE.

    READ   Malek's request, Ahmed's manifest + receipts + warehouse, Rabeb's KPI catalog
    WORK   compile the SQL from the catalog, run it, run the BO3-03 checks, then the insight agent
           (step 6, analysis/insight_agent.py: Groq, with a deterministic fallback)
    LOG    one audit line per important decision (KPI version chosen, each check, result)
    WRITE  analysis_result.json + result.parquet, then return the AgentResult

    python -m analysis.analyst dev_001      # run it on the mini warehouse
"""
import sys

import duckdb

from analysis.insight_agent import write_insights
from analysis.sql_compiler import CompileError, compile_query
from analysis.validations import run_checks
from contracts import AgentResult, AgentStatus, RunContext, context_for, save
from contracts.analysis import AnalysisResult
from contracts.registry import read_output
from contracts.semantic import KpiCatalog, load_yaml


def run(ctx: RunContext) -> AgentResult:
    # ---- 1. READ: read_output validates every file against its contract ----------------------
    request = read_output(ctx.inputs["request"], "request.request")
    manifest = read_output(ctx.inputs["manifest"], "etl.manifest")
    receipts = read_output(ctx.inputs["receipts"], "etl.receipts")
    catalog = load_yaml(KpiCatalog, ctx.inputs["catalog"])
    read = [str(ctx.inputs[k]) for k in ("request", "manifest", "receipts", "catalog")]

    # ---- 2. WORK: SQL built from the approved definition, never written by hand ----------------
    try:
        q = compile_query(request, catalog, manifest)
    except CompileError as e:
        ctx.log("compile_query", f"refused: {e}", inputs=read, evidence={"metric": request.metric,
                                                                         "dimensions": request.dimensions})
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, message=str(e))
    rule = f"kpi:{q.kpi.ref}"
    ctx.log("kpi_version_chosen", f"{request.metric} computed with {q.kpi.ref}", inputs=read,
            rule_version=rule, evidence={"expression": q.kpi.expression, "table": q.kpi.table,
                                         "grain": q.kpi.grain, "filters": q.kpi.filters, "sql": q.sql})

    con = duckdb.connect(str(ctx.inputs["warehouse"]), read_only=True)
    try:
        df = con.execute(q.sql).df()
        totals = df.groupby("period")["value"].sum().to_dict()
        checks = run_checks(con, q, manifest, receipts, totals)

        # ---- 3. LOG: one line per BO3-03 check, with its numbers -----------------------------
        for c in checks:
            ctx.log(f"check_{c.name}", "PASSED" if c.passed else "FAILED", rule_version=rule,
                    evidence={"detail": c.detail})
        all_passed = all(c.passed for c in checks)

        # Insights only on validated numbers (the agent needs the open warehouse for its tool)
        insights = (write_insights(ctx, con, q, request, catalog, manifest, receipts, totals, df)
                    if all_passed else [])
    finally:
        con.close()

    current = float(totals.get("current", 0.0))
    previous = float(totals["previous"]) if "previous" in totals else None
    change = round((current - previous) / previous, 4) if previous else None

    # ---- 4. WRITE: result.parquet (dimensions, period, value) + analysis_result.json ---------
    data_path = ctx.output("data")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(data_path, index=False)
    result = AnalysisResult(
        request=request, kpi=q.kpi.ref, sql=q.sql, data_file=data_path.name, rows=len(df),
        value_current=round(current, 2), value_previous=None if previous is None else round(previous, 2),
        change_pct=change, unit=q.kpi.unit, validations=checks,
        insights=insights)
    result_path = save(result, ctx.output("result"))
    ctx.log("result_written", f"{q.kpi.ref} = {result.value_current} {q.kpi.unit}; "
                              f"validation {'PASSED' if all_passed else 'FAILED'}",
            outputs=[str(result_path), str(data_path)], rule_version=rule,
            evidence={"value_current": result.value_current, "value_previous": result.value_previous,
                      "failed_checks": [c.name for c in checks if not c.passed]})

    status = AgentStatus.SUCCESS if all_passed else AgentStatus.FAILED
    failed = ", ".join(c.name for c in checks if not c.passed)
    message = (f"{q.kpi.ref} computed and validated ({len(checks)} checks passed)." if all_passed
               else f"{q.kpi.ref} computed but failed BO3-03 checks: {failed}.")
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=status,
                       outputs={"result": result_path, "data": data_path}, message=message)


if __name__ == "__main__":
    out = run(context_for("analysis", sys.argv[1] if len(sys.argv) > 1 else "dev_001"))
    print(f"{out.status.value}: {out.message}")
    for key, path in out.outputs.items():
        print(f"  {key}: {path}")
