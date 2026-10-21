"""Tasnim's routes (BO4-12 comparisons + BO3 Auditor), as an APIRouter.

The team's FastAPI app adds them in ONE line:

    from api.router import router as tasnim_router
    app.include_router(tasnim_router, prefix="/api")

The routes hold NO business logic: they read the contract files of runs/<run_id>/, call the same
functions as Streamlit (comparisons.checker, comparisons.values, auditor.why, contracts.audit)
and return the contracts as they are. Writes only go through record_decision() and new custom
comparisons, both journaled. Custom comparisons and their decisions go to the UI journal
(runs/ui_journal.db), never to the real one. Which journals are visible: BIFLOW_JOURNALS.
"""
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path as PathParam, Query

from api.schemas import (Dataset, DatasetKpi, DashboardState, Decision, ExplanationPage, JournalInfo, NewComparison,
                         NewComparisonResult, RunInfo, RunSummary, WhyQuestion)
from auditor import journals
from auditor.why import WhyAgent
from comparisons.checker import record_decision, run as run_checker
from comparisons.values import KpiBreakdown, dashboard_periods, kpi_by_dimension
from contracts.agent import RunContext
from contracts.audit import IntegrityReport, JournalEntry, read_events, verify_journal
from contracts.common import load, save
from contracts.i18n import DEFAULT_LANG, from_accept_language, localize
from contracts.comparisons import ComparisonReport
from contracts.pipeline import REPO_ROOT, RUNS_ROOT, context_for, output_path
from contracts.registry import CONTRACT_OF
from contracts.semantic import AnalysisRequest, KpiCatalog, load_yaml
from contracts.warehouse import WarehouseManifest
from contracts.xai import AnomalyExplanation, DriftReport, WhyAnswer

RUN_ID = r"^[A-Za-z0-9_-]{1,64}$"          # no dot, no slash: a run id can never leave runs/
RunId = Annotated[str, PathParam(pattern=RUN_ID)]


def reader_lang(lang: Literal["fr", "en"] | None = Query(None, description="Language of the texts (fr / en). "
                                                         "Default: the Accept-Language header, else French."),
                accept_language: str | None = Header(None)) -> str:
    """The language the reader wants. Texts are stored in English and rendered on the way out."""
    return lang or from_accept_language(accept_language) or DEFAULT_LANG


Lang = Annotated[str, Depends(reader_lang)]


def make_router(runs_root: Path = RUNS_ROOT, repo_root: Path = REPO_ROOT, llm=None, writer=None) -> APIRouter:
    """All of Tasnim's routes. llm / writer replace the LLM calls of the why? agent (tests);
    None = the real ones. The team app mounts it with: app.include_router(router, prefix="/api")."""
    runs_root, repo_root = Path(runs_root), Path(repo_root)
    router = APIRouter()
    visible = journals.visible()
    JournalId = Annotated[str, PathParam(pattern="^(" + "|".join(visible) + ")$")]

    # ---- helpers -------------------------------------------------------------------------
    def path_of(run_id: str, ref: str) -> Path:
        step, key = ref.split(".")
        return output_path(run_id, step, key, runs_root)

    def read(run_id: str, ref: str):
        p = path_of(run_id, ref)
        return load(CONTRACT_OF[ref], p) if p.exists() else None

    def need(run_id: str, ref: str):
        if not (runs_root / run_id).is_dir():
            raise HTTPException(404, f"Unknown run '{run_id}'.")
        obj = read(run_id, ref)
        if obj is None:
            raise HTTPException(404, f"Run '{run_id}' has no {ref.replace('.', ' ')} yet.")
        return obj

    def journal_of(run_id: str) -> Path:
        return journals.journal_for(run_id, runs_root)

    def ctx_kwargs(run_id: str) -> dict:
        return {"runs_root": runs_root, "repo_root": repo_root, "journal": journal_of(run_id)}

    def run_ids() -> list[str]:
        return sorted(p.name for p in runs_root.iterdir() if p.is_dir()) if runs_root.exists() else []

    # ---- general -----------------------------------------------------------------------------
    @router.get("/runs", response_model=list[RunInfo], tags=["runs"])
    def list_runs():
        refs = {"request": "request.request", "comparison": "comparisons.report",
                "anomalies": "profiling.anomalies", "explanations": "auditor.explanations",
                "drift": "auditor.drift"}
        return [RunInfo(run_id=r, base_run=journals.base_run(r, runs_root),
                        journal=journals.journal_id_for(r, runs_root),
                        has={k: path_of(r, ref).exists() for k, ref in refs.items()})
                for r in run_ids()]

    @router.get("/datasets", response_model=list[Dataset], tags=["runs"])
    def datasets():
        """Runs whose data can answer a NEW question (POST /comparisons): coverage profile,
        warehouse and catalog present. Custom runs (custom_*) reuse another run's data: left out."""
        out = []
        for r in run_ids():
            if r.startswith("custom_"):
                continue
            ctx = context_for("comparisons", r, runs_root, repo_root)
            paths = ctx.inputs
            if not all(Path(paths[k]).exists() for k in ("coverage", "warehouse", "manifest", "catalog")):
                continue
            cov = load(CONTRACT_OF["profiling.coverage"], paths["coverage"])
            catalog = load_yaml(KpiCatalog, paths["catalog"])
            out.append(Dataset(
                run_id=r, first_day=min(t.first_day for t in cov.tables),
                last_day=max(t.last_day for t in cov.tables),
                kpis=[DatasetKpi(name=k.name, ref=k.ref, unit=k.unit, description=k.description,
                                 allowed_dimensions=k.allowed_dimensions) for k in catalog.kpis],
                dimensions={d.name: d.description for d in catalog.dimensions}))
        return out

    @router.get("/runs/{run_id}", response_model=RunSummary, tags=["runs"])
    def run_summary(run_id: RunId, lang: Lang):
        """Everything the result screen needs: question, BO4-12 verdict, which periods the
        dashboard uses, integrity of the journal, anomalies, drift."""
        if not (runs_root / run_id).is_dir():
            raise HTTPException(404, f"Unknown run '{run_id}'.")
        request, report = read(run_id, "request.request"), read(run_id, "comparisons.report")
        dashboard = None
        if request is not None:
            periods, source = dashboard_periods(report, request)
            dashboard = DashboardState(periods_source=source, period=periods[0] if periods else None,
                                       compare_to=periods[1] if periods else None)
        jid = journals.journal_id_for(run_id, runs_root)
        anomalies = read(journals.base_run(run_id, runs_root), "profiling.anomalies")
        drift = read(run_id, "auditor.drift")
        return RunSummary(run_id=run_id, base_run=journals.base_run(run_id, runs_root), journal=jid,
                          request=request, comparison=localize(report, lang), dashboard=dashboard,
                          integrity=verify_journal(journals.journal_path(jid, runs_root)) if jid else None,
                          anomalies=anomalies.n_anomalies if anomalies else None,
                          drift_status=drift.status if drift else None)

    # ---- BO4-12 --------------------------------------------------------------------------------
    @router.get("/runs/{run_id}/comparison", response_model=ComparisonReport, tags=["BO4-12 comparisons"])
    def comparison(run_id: RunId, lang: Lang):
        return localize(need(run_id, "comparisons.report"), lang)

    @router.post("/runs/{run_id}/comparison/decision", response_model=ComparisonReport,
              tags=["BO4-12 comparisons"])
    def decide(run_id: RunId, body: Decision, lang: Lang):
        """The user accepts a fix, keeps the comparison as asked (rejected), or goes back to
        pending. Written in the audit journal. Nothing is applied without it."""
        need(run_id, "comparisons.report")
        try:
            return localize(record_decision(run_id, body.decision, body.chosen_fix, **ctx_kwargs(run_id)), lang)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.post("/comparisons", response_model=NewComparisonResult, tags=["BO4-12 comparisons"])
    def new_comparison(body: NewComparison, lang: Lang):
        """Run the real BO4-12 agent on a new question, on the data of an existing run.
        Creates a new run custom_<id> (logged in the UI journal, never in the real one)."""
        base = body.base_run
        inputs = dict(context_for("comparisons", base, runs_root, repo_root).inputs)
        missing = [k for k in ("coverage", "warehouse", "manifest", "receipts", "catalog")
                   if not Path(inputs[k]).exists()]
        if missing:
            raise HTTPException(404, f"Run '{base}' lacks: {', '.join(missing)}.")
        catalog = load_yaml(KpiCatalog, inputs["catalog"])
        kpi = next((k for k in catalog.kpis if k.name == body.metric), None)
        if kpi is None:
            raise HTTPException(400, f"Unknown KPI '{body.metric}'. Known: {[k.name for k in catalog.kpis]}")
        bad = [d for d in body.dimensions if d not in kpi.allowed_dimensions]
        if bad:
            raise HTTPException(400, f"Dimensions {bad} not allowed for {kpi.ref}: {kpi.allowed_dimensions}")

        run_id = f"custom_{uuid.uuid4().hex[:8]}"
        run_dir = runs_root / run_id
        own_static = runs_root / base / "static"
        if own_static.is_dir():                                    # the base run's own catalog
            shutil.copytree(own_static, run_dir / "static")
        req = AnalysisRequest(question=body.question, metric=body.metric, dimensions=body.dimensions,
                              filters=body.filters, period=body.period, compare_to=body.compare_to)
        inputs["request"] = save(req, output_path(run_id, "request", "request", runs_root))
        inputs["result"] = output_path(run_id, "analysis", "result", runs_root)   # none: recomputed
        (run_dir / "base_run.txt").write_text(base, encoding="utf-8")
        ctx = RunContext(run_id=run_id, agent="comparisons", inputs=inputs, output_dir=run_dir / "comparisons",
                         params={"llm": body.llm, "language": body.lang or lang},
                         journal=journals.journal_path(journals.CUSTOM_JOURNAL, runs_root))
        try:
            res = run_checker(ctx)
        except ValueError as e:
            raise HTTPException(400, str(e))
        report = load(ComparisonReport, res.outputs["report"])
        return NewComparisonResult(run_id=run_id, report=localize(report, body.lang or lang))

    @router.get("/runs/{run_id}/dashboard", response_model=KpiBreakdown, tags=["BO4-12 comparisons"])
    def dashboard(run_id: RunId, limit: int = Query(10, ge=1, le=100)):
        """The KPI by the first requested dimension, for the periods the user's decision fixes.
        409 while a blocked comparison waits for the user's decision."""
        request = need(run_id, "request.request")
        periods, source = dashboard_periods(read(run_id, "comparisons.report"), request)
        if periods is None:
            raise HTTPException(409, "The comparison is blocked: waiting for the user's decision.")
        data = journals.base_run(run_id, runs_root)
        ctx = context_for("comparisons", data, runs_root, repo_root)
        if not Path(ctx.inputs["warehouse"]).exists():
            raise HTTPException(404, f"Run '{data}' has no warehouse.")
        return kpi_by_dimension(ctx.inputs["warehouse"], load(WarehouseManifest, ctx.inputs["manifest"]),
                                load_yaml(KpiCatalog, ctx.inputs["catalog"]), request, *periods,
                                periods_source=source, limit=limit)

    # ---- BO3: explanations ---------------------------------------------------------------------
    @router.get("/runs/{run_id}/explanations", response_model=ExplanationPage, tags=["BO3 auditor"])
    def explanations(run_id: RunId, lang: Lang, anomalies_only: bool = True,
                     offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200)):
        rep = need(run_id, "auditor.explanations")
        items = [e for e in rep.explanations if e.is_anomaly or not anomalies_only]
        return ExplanationPage(run_id=run_id, model_version=rep.model_version, explainer=rep.explainer,
                               total=len(items), offset=offset, items=localize(items[offset:offset + limit], lang))

    @router.get("/runs/{run_id}/explanations/{row_key}", response_model=AnomalyExplanation, tags=["BO3 auditor"])
    def explanation(run_id: RunId, row_key: str, lang: Lang):
        rep = need(run_id, "auditor.explanations")
        e = next((x for x in rep.explanations if x.row_key == row_key), None)
        if e is None:
            raise HTTPException(404, f"No explanation for row '{row_key}' in run '{run_id}'.")
        return localize(e, lang)

    # ---- BO3: why? -----------------------------------------------------------------------------
    @router.post("/runs/{run_id}/why", response_model=WhyAnswer, tags=["BO3 auditor"])
    def why(run_id: RunId, body: WhyQuestion):
        """The why? agent: LLM + read-only tools. Every number and citation is checked; if the
        LLM fails, a deterministic answer from the journal is returned (source = 'template').
        Answers in body.lang, or else in the language of the question (detected)."""
        if not (runs_root / run_id).is_dir():
            raise HTTPException(404, f"Unknown run '{run_id}'.")
        overrides = {k: v for k, v in (("llm", llm), ("writer", writer)) if v is not None}
        agent = WhyAgent(run_id, journal=journal_of(run_id), runs_root=runs_root, repo_root=repo_root,
                         language=body.lang, **overrides)
        return agent.ask(body.question)

    # ---- BO3: journal ---------------------------------------------------------------------------
    @router.get("/runs/{run_id}/journal", response_model=list[JournalEntry], tags=["BO3 audit journal"])
    def run_journal(run_id: RunId, include_llm: bool = False):
        """Decisions of this run, oldest first. include_llm adds the LLM calls and why? answers."""
        jid = journals.journal_id_for(run_id, runs_root)
        if jid is None:
            raise HTTPException(404, f"No journal holds run '{run_id}'.")
        events = read_events(journals.journal_path(jid, runs_root), run_id=run_id)
        return [e for e in events if include_llm or not (e.step.startswith("llm:") or e.step == "why_answer")]

    @router.get("/journals", response_model=list[JournalInfo], tags=["BO3 audit journal"])
    def list_journals():
        out = []
        for jid, path in journals.existing(runs_root).items():
            events = read_events(path)
            out.append(JournalInfo(id=jid, label=journals.JOURNALS[jid][0], entries=len(events),
                                   runs=sorted({e.run_id for e in events}), intact=verify_journal(path).ok))
        return out

    def journal_file(journal_id: str) -> Path:
        path = journals.journal_path(journal_id, runs_root)
        if not path.exists():
            raise HTTPException(404, f"Journal '{journal_id}' does not exist yet.")
        return path

    @router.get("/journals/{journal_id}/entries", response_model=list[JournalEntry], tags=["BO3 audit journal"])
    def journal_entries(journal_id: JournalId, run_id: str | None = None, agent: str | None = None,
                        limit: int = Query(500, ge=1, le=5000)):
        return read_events(journal_file(journal_id), run_id=run_id, agent=agent)[-limit:]

    @router.get("/journals/{journal_id}/verify", response_model=IntegrityReport, tags=["BO3 audit journal"])
    def journal_verify(journal_id: JournalId):
        """Recompute the whole hash chain: any modified or deleted entry is found."""
        return verify_journal(journal_file(journal_id))

    # ---- BO3: drift -----------------------------------------------------------------------------
    @router.get("/runs/{run_id}/drift", response_model=DriftReport, tags=["BO3 drift"])
    def run_drift(run_id: RunId, lang: Lang):
        return localize(need(run_id, "auditor.drift"), lang)

    @router.get("/drift", response_model=list[DriftReport], tags=["BO3 drift"])
    def all_drift(lang: Lang):
        """Drift reports of every monitored run (reports 'not_available' are left out)."""
        reports = [read(r, "auditor.drift") for r in run_ids()]
        return [localize(d, lang) for d in reports if d is not None and d.status != "not_available"]

    return router


router = make_router()
