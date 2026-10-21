"""Can every KPI of the catalog be computed on this run's warehouse? Run it right after the ETL.

    python -m tools.integration.check_warehouse integ_001

For each KPI, and each of its allowed dimensions, the Analyst's SQL is compiled from the catalog and
executed on the warehouse (read-only), and the columns the comparisons need are checked.
If something fails, the usual cause is the ETL plan approved by a human: llama3 refused a relationship
(e.g. payments -> orders), so the fact view lost a column. The links the plan did NOT keep are listed:
edit runs/<run>/etl/warehouse_proposal.json (design.relationships), approve the new file and rebuild.
"""
import json
import sys
from pathlib import Path

import duckdb

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R))

from analysis.sql_compiler import CompileError, compile_query            # noqa: E402
from comparisons.data import missing_kpi_columns                         # noqa: E402
from contracts.common import Period, load                                # noqa: E402
from contracts.pipeline import context_for                               # noqa: E402
from contracts.semantic import AnalysisRequest, KpiCatalog, load_yaml    # noqa: E402
from contracts.warehouse import WarehouseManifest                        # noqa: E402


def check(run_id: str, runs_root: Path = R / "runs") -> list[str]:
    ctx = context_for("analysis", run_id, runs_root=runs_root, repo_root=R)
    catalog = load_yaml(KpiCatalog, ctx.inputs["catalog"])
    manifest = load(WarehouseManifest, ctx.inputs["manifest"])
    con = duckdb.connect(str(ctx.inputs["warehouse"]), read_only=True)
    period, before = Period(start="2018-08-01", end="2018-08-31"), Period(start="2018-07-01", end="2018-07-31")
    problems = []
    for kpi in catalog.kpis:
        if missing := missing_kpi_columns(kpi, manifest):
            problems.append(f"{kpi.ref}: {kpi.table} has no {', '.join(missing)} (needed by the comparisons)")
        for dims in [[]] + [[d] for d in kpi.allowed_dimensions]:
            req = AnalysisRequest(question="check", metric=kpi.name, dimensions=dims, period=period, compare_to=before)
            label = f"{kpi.ref} by {dims[0]}" if dims else kpi.ref
            try:
                q = compile_query(req, catalog, manifest)
                for sql in (q.sql, q.total_sql, q.count_sql, q.joined_count_sql):
                    if sql:
                        con.execute(sql).fetchall()
            except (CompileError, duckdb.Error) as e:
                problems.append(f"{label}: {type(e).__name__}: {str(e).splitlines()[0][:160]}")
    con.close()
    return problems


def unkept_links(run_id: str, runs_root: Path = R / "runs") -> list[str]:
    proposal = runs_root / run_id / "etl" / "warehouse_proposal.json"
    if not proposal.exists():
        return []
    env = json.loads(proposal.read_text(encoding="utf-8"))
    kept = set(env["design"]["relationships"])
    src = {t: info.get("source", t) for t, info in env["tables"].items()}
    return [f'{c["id"]}: {src[c["child"]]} -> {src[c["parent"]]}' for c in env["candidates"] if c["id"] not in kept]


if __name__ == "__main__":
    run = sys.argv[1] if len(sys.argv) > 1 else "integ_001"
    problems = check(run)
    if not problems:
        print(f"OK  every KPI of the catalog can be computed on runs/{run}/etl/warehouse.duckdb")
        sys.exit(0)
    print(f"!!  {len(problems)} problem(s) on runs/{run}:")
    for p in problems:
        print("   -", p)
    links = unkept_links(run)
    if links:
        print("\nRelationships found in the data but NOT kept by the approved ETL plan:")
        for link in links:
            print("   -", link)
        print("Add the needed ids to design.relationships in runs/<run>/etl/warehouse_proposal.json,"
              " delete the other files of runs/<run>/etl/, approve the new file's sha256 and rebuild.")
    sys.exit(1)
