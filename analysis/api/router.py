"""Rabeb's routes (step 5: the Analyst, the KPI catalog, the KPI proposer), as an APIRouter.

The team's FastAPI app adds them in ONE line, next to Tasnim's:

    from analysis.api.router import router as analyst_router
    app.include_router(analyst_router, prefix="/api")

No business logic here: the routes call the same functions as the Streamlit pages
(analysis.analyst, sql_compiler + validations, kpi_proposer) and return the contracts as they are.
Only POST /runs/{run_id}/analysis writes (the Analyst's own outputs + its journal lines).
"""
from pathlib import Path
from typing import Annotated

import duckdb
import pandas as pd
from fastapi import APIRouter, HTTPException, Path as PathParam

from analysis.analyst import run as run_analyst
from analysis.api.schemas import (Insights, KpiPreview, KpiPreviewResult, KpiProposal, ProposeKpis, ResultRows,
                                  RunAnalysis, RunAnalysisResult)
from analysis.kpi_proposer import propose
from analysis.sql_compiler import CompileError, compile_query
from analysis.validations import run_checks
from contracts.analysis import AnalysisResult
from contracts.audit import DEFAULT_JOURNAL, read_events
from contracts.common import load
from contracts.pipeline import REPO_ROOT, RUNS_ROOT, context_for, output_path
from contracts.registry import CONTRACT_OF
from contracts.semantic import AnalysisRequest, Glossary, KpiCatalog, load_yaml

RUN_ID = r"^[A-Za-z0-9_-]{1,64}$"          # no dot, no slash: a run id can never leave runs/
RunId = Annotated[str, PathParam(pattern=RUN_ID)]


def make_router(runs_root: Path = RUNS_ROOT, repo_root: Path = REPO_ROOT,
                journal: Path = DEFAULT_JOURNAL) -> APIRouter:
    runs_root, repo_root, journal = Path(runs_root), Path(repo_root), Path(journal)
    router = APIRouter()

    # ---- helpers -------------------------------------------------------------------------
    def ctx(run_id: str, params: dict | None = None):
        return context_for("analysis", run_id, runs_root, repo_root, journal, params)

    def read(run_id: str, ref: str):
        step, key = ref.split(".")
        p = output_path(run_id, step, key, runs_root)
        return load(CONTRACT_OF[ref], p) if p.exists() else None

    def need_run(run_id: str) -> None:
        if not (runs_root / run_id).is_dir():
            raise HTTPException(404, f"Unknown run '{run_id}'.")

    def need(run_id: str, ref: str):
        need_run(run_id)
        obj = read(run_id, ref)
        if obj is None:
            raise HTTPException(404, f"Run '{run_id}' has no {ref.replace('.', ' ')} yet.")
        return obj

    def catalog_of(run_id: str | None = None) -> KpiCatalog:
        path = ctx(run_id).inputs["catalog"] if run_id else repo_root / "kpi" / "catalog.yaml"
        return load_yaml(KpiCatalog, path)

    # ---- the Analyst ------------------------------------------------------------------------
    @router.post("/runs/{run_id}/analysis", response_model=RunAnalysisResult, tags=["analysis"])
    def analyse(run_id: RunId, body: RunAnalysis):
        """Run the Analyst (step 5) on a run: SQL compiled from the catalog, the 4 BO3-03 checks,
        then the insights. Needs the run's request and warehouse. Status 'failed' = a check failed
        or the request asks for something the catalog does not allow (see message)."""
        need_run(run_id)
        c = ctx(run_id, {"llm": body.llm})
        missing = [k for k, p in c.inputs.items() if not Path(p).exists()]
        if missing:
            raise HTTPException(409, f"Run '{run_id}' is not ready for the Analyst, missing: {', '.join(missing)}.")
        out = run_analyst(c)
        return RunAnalysisResult(agent=out, result=read(run_id, "analysis.result"))

    @router.get("/runs/{run_id}/analysis", response_model=AnalysisResult, tags=["analysis"])
    def analysis(run_id: RunId):
        """The Analyst's answer: value, comparison, KPI version, exact SQL, BO3-03 checks, insights."""
        return need(run_id, "analysis.result")

    @router.get("/runs/{run_id}/analysis/rows", response_model=ResultRows, tags=["analysis"])
    def rows(run_id: RunId):
        """result.parquet as JSON (dimensions..., period, value): the data of the charts."""
        need(run_id, "analysis.result")
        df = pd.read_parquet(output_path(run_id, "analysis", "data", runs_root))
        return ResultRows(run_id=run_id, columns=list(df.columns), rows=df.to_dict(orient="records"))

    @router.get("/runs/{run_id}/analysis/insights", response_model=Insights, tags=["analysis"])
    def insights(run_id: RunId):
        """The insights, and who wrote them: 'llm' (every number checked) or 'fallback'."""
        result = need(run_id, "analysis.result")
        written = [e for e in read_events(journal, run_id=run_id, agent="analysis") if e.step == "insights_written"]
        return Insights(run_id=run_id, source=written[-1].evidence.get("source") if written else None,
                        insights=result.insights)

    # ---- the KPI catalog ---------------------------------------------------------------------
    @router.get("/catalog", response_model=KpiCatalog, tags=["KPI catalog"])
    def catalog():
        """The approved KPIs (formula, version, unit, filters, population, allowed dimensions)."""
        return catalog_of()

    @router.get("/glossary", response_model=Glossary, tags=["KPI catalog"])
    def glossary():
        """The manager's words -> the catalog's names (read by the request agent)."""
        return load_yaml(Glossary, repo_root / "semantic" / "glossary.yaml")

    @router.post("/kpis/preview", response_model=KpiPreviewResult, tags=["KPI catalog"])
    def preview(body: KpiPreview):
        """Compute a KPI on a run's warehouse with the Analyst's compiler and BO3-03 checks.
        Read-only: nothing is written, nothing is journaled."""
        manifest = need(body.run_id, "etl.manifest")
        cat = catalog_of(body.run_id)
        request = AnalysisRequest(question="KPI preview", metric=body.metric, dimensions=body.dimensions,
                                  period=body.period, compare_to=body.compare_to)
        try:
            q = compile_query(request, cat, manifest)
        except CompileError as e:
            raise HTTPException(400, str(e))
        con = duckdb.connect(str(output_path(body.run_id, "etl", "warehouse", runs_root)), read_only=True)
        try:
            df = con.execute(q.sql).df()
            totals = df.groupby("period")["value"].sum().to_dict()
            checks = run_checks(con, q, manifest, read(body.run_id, "etl.receipts"), totals)
        finally:
            con.close()
        return KpiPreviewResult(kpi=q.kpi.ref, unit=q.kpi.unit, sql=q.sql,
                                rows=df.to_dict(orient="records"), validations=checks)

    @router.post("/runs/{run_id}/kpi-proposal", response_model=KpiProposal, tags=["KPI catalog"])
    def kpi_proposal(run_id: RunId, body: ProposeKpis):
        """A DRAFT catalog + glossary for this run's warehouse (any dataset). Approved KPIs keep their
        name, version, unit and filters. Nothing is written into kpi/catalog.yaml: a human reviews it."""
        manifest = need(run_id, "etl.manifest")
        glossary_file = repo_root / "semantic" / "glossary.yaml"
        cat, gloss, source = propose(manifest, output_path(run_id, "etl", "warehouse", runs_root),
                                     use_llm=body.llm, approved=catalog_of(run_id),
                                     approved_glossary=load_yaml(Glossary, glossary_file) if glossary_file.exists() else None)
        return KpiProposal(run_id=run_id, source=source, catalog=cat, glossary=gloss)

    return router


router = make_router()
