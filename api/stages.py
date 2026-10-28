"""What every agent of the pipeline produced for one run, for the app (read-only), and the
question parser of Malek (BO4-06) as a live route.

    GET  /runs/{run_id}/pipeline     the outputs of the 13 steps, in one call
    POST /parse                      a question in plain words -> a proposed AnalysisRequest

Rules, as for the rest of the API:
  * only CONTRACT files are read (never the *.bo2.json side files: they hold absolute paths);
  * nothing is recomputed here: what is shown is what the agents wrote in runs/<run_id>/;
  * a custom run (custom_*, created by POST /comparisons) owns its request, analysis and
    comparison; the data steps (similarity ... lineage) come from its base run, said in `source_run`.
"""
import json
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Path as PathParam
from pydantic import BaseModel, Field

from auditor import journals
from contracts.agent import AgentStatus, RunContext
from contracts.analysis import AnalysisResult
from contracts.common import load, save
from contracts.intake import ColumnTypesReport, SimilarityReport, Upload
from contracts.privacy import PiiColumn
from contracts.quality import RuleApplication
from contracts.pipeline import STEPS, context_for, output_path
from contracts.registry import CONTRACT_OF
from contracts.semantic import AnalysisRequest, KpiCatalog, load_yaml
from contracts.warehouse import LineageEdge, LineageNode, TransformationReceipts, WarehouseManifest

# Steps computed ONCE on the dataset (shown from the base run) / for EACH question (from the run itself)
DATASET_STEPS = ["upload", "similarity", "column_types", "pii", "profiling", "cleaning", "etl", "lineage"]
QUESTION_STEPS = ["request", "analysis", "comparisons", "dashboard", "auditor"]
RunId = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{1,64}$")]   # no dot, no slash
MAIN_OUTPUT = {"upload": "upload.upload", "similarity": "similarity.report", "column_types": "column_types.report",
               "pii": "pii.report", "profiling": "profiling.profile", "cleaning": "cleaning.report",
               "etl": "etl.manifest", "lineage": "lineage.graph", "request": "request.request",
               "analysis": "analysis.result", "comparisons": "comparisons.report", "dashboard": "dashboard.spec",
               "auditor": "auditor.explanations"}


# ---- response models (contracts are reused as they are when they hold no local path) -------------
class StageInfo(BaseModel):
    step: str
    owner: str
    scope: Literal["dataset", "question"]
    available: bool                     # the step's main output file exists
    source_run: str                     # the run whose files are shown


class PiiSummary(BaseModel):
    policy_version: str
    actions: dict[str, int]             # action -> number of columns (kept, pseudonymized, masked...)
    columns: list[PiiColumn]            # every column of the contract


class MissingColumn(BaseModel):
    name: str
    missing_pct: float


class TableProfileSummary(BaseModel):
    table: str
    rows: int
    duplicate_rows: int
    columns: int
    missing_cells_pct: float            # over the whole table
    most_missing: list[MissingColumn]   # the (up to) 3 columns with the most missing values


class CoverageSummary(BaseModel):
    table: str
    date_column: str
    first_day: date
    last_day: date
    days: int


class AnomalySummary(BaseModel):
    table: str
    model: str
    model_version: str
    features: list[str]
    n_rows: int
    n_anomalies: int
    contamination: float | None = None


class ProfilingSummary(BaseModel):
    tables: list[TableProfileSummary]
    coverage: list[CoverageSummary]
    anomalies: AnomalySummary | None = None


class CleaningSummary(BaseModel):
    playbook: str
    rules: int                          # rules applied
    rules_with_effect: int              # rules that changed at least one row
    rows_changed: int
    applied: list[RuleApplication]      # largest effect first
    rows_before: dict[str, int]
    rows_after: dict[str, int]


class EtlView(BaseModel):
    manifest: WarehouseManifest
    receipts: TransformationReceipts | None = None


class LineagePath(BaseModel):
    kpi: str                            # e.g. "Revenue@2.0"
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    total_nodes: int                    # size of the whole graph (the path is a part of it)
    total_edges: int


class PipelineView(BaseModel):
    run_id: str
    base_run: str
    stages: list[StageInfo]
    question: str | None = None
    tables: dict[str, str] | None = None                    # upload: table -> file name
    similarity: SimilarityReport | None = None
    column_types: ColumnTypesReport | None = None
    pii: PiiSummary | None = None
    profiling: ProfilingSummary | None = None
    cleaning: CleaningSummary | None = None
    etl: EtlView | None = None
    lineage: LineagePath | None = None
    request: AnalysisRequest | None = None
    analysis: AnalysisResult | None = None


class ChartOption(BaseModel):
    chart_type: str
    score: float
    eligible: bool
    reason: str


class ChartView(BaseModel):
    chart_id: str
    chart_type: str                     # kpi_card, bar, line, pie, table (map: not rendered yet)
    title: str
    x: str | None = None
    y: str
    color: str | None = None
    reason: str                         # why the dashboard agent chose this chart
    rows: list[dict]                    # the prepared data (at most 200 rows)
    alternatives: list[ChartOption] = Field(default_factory=list)   # every type considered, best first


class DashboardView(BaseModel):
    """Samar's dashboard agent (dashboard_ai): the charts it chose, their data and its warnings."""
    title: str
    question: str
    kpi: str
    charts: list[ChartView]
    warnings: list[str]
    comparison_shown: bool | None = None
    rules_version: str | None = None


class ParseQuestion(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    base_run: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Run whose catalog / glossary are used")


class ParsedQuestion(BaseModel):
    status: Literal["success", "needs_review", "failed"]
    message: str
    request: AnalysisRequest | None = None


# ---- the read side ---------------------------------------------------------------------------------
def kpi_path(graph, kpi_ref: str) -> LineagePath | None:
    """Every node upstream of the KPI (raw column -> pii -> clean -> warehouse -> KPI)."""
    target = f"kpi:{kpi_ref}"
    if not any(n.id == target for n in graph.nodes):
        return None
    incoming = defaultdict(list)
    for e in graph.edges:
        incoming[e.target].append(e)
    keep, edges, todo = {target}, [], [target]
    while todo:
        for e in incoming[todo.pop()]:
            edges.append(e)
            if e.source not in keep:
                keep.add(e.source)
                todo.append(e.source)
    return LineagePath(kpi=kpi_ref, nodes=[n for n in graph.nodes if n.id in keep], edges=edges,
                       total_nodes=len(graph.nodes), total_edges=len(graph.edges))


def make_stages_router(runs_root: Path, repo_root: Path) -> APIRouter:
    router = APIRouter()

    def read(run_id: str, ref: str):
        step, key = ref.split(".")
        p = output_path(run_id, step, key, runs_root)
        return load(CONTRACT_OF[ref], p) if p.exists() else None

    @router.get("/runs/{run_id}/pipeline", response_model=PipelineView, tags=["pipeline"])
    def pipeline(run_id: RunId):
        """What each agent of the DAG wrote for this run. Data steps come from the base run."""
        if not (runs_root / run_id).is_dir():
            raise HTTPException(404, f"Unknown run '{run_id}'.")
        base = journals.base_run(run_id, runs_root)
        source = {s: (base if s in DATASET_STEPS else run_id) for s in STEPS}
        # the Auditor's SHAP explanations and drift are about the DATA: a custom run shows its base run's
        if not output_path(run_id, *MAIN_OUTPUT["auditor"].split("."), runs_root).exists():
            source["auditor"] = base
        stages = [StageInfo(step=s, owner=STEPS[s].owner, scope="dataset" if s in DATASET_STEPS else "question",
                            available=output_path(source[s], *MAIN_OUTPUT[s].split("."), runs_root).exists(),
                            source_run=source[s]) for s in STEPS]
        view = PipelineView(run_id=run_id, base_run=base, stages=stages)

        if up := read(base, "upload.upload"):
            view.question, view.tables = up.question, up.tables
        view.similarity = read(base, "similarity.report")
        view.column_types = read(base, "column_types.report")

        if pii := read(base, "pii.report"):
            actions = defaultdict(int)
            for c in pii.columns:
                actions[c.action] += 1
            view.pii = PiiSummary(policy_version=pii.policy_version, actions=dict(actions), columns=pii.columns)

        profile, coverage, anomalies = (read(base, r) for r in
                                        ("profiling.profile", "profiling.coverage", "profiling.anomalies"))
        if profile or coverage or anomalies:
            tables = []
            for t in (profile.tables if profile else []):
                cells = t.rows * max(len(t.columns), 1)
                missing = sum(c.missing for c in t.columns)
                worst = sorted(t.columns, key=lambda c: -c.missing_pct)[:3]
                tables.append(TableProfileSummary(
                    table=t.table, rows=t.rows, duplicate_rows=t.duplicate_rows, columns=len(t.columns),
                    missing_cells_pct=round(100 * missing / cells, 2) if cells else 0.0,
                    most_missing=[MissingColumn(name=c.name, missing_pct=c.missing_pct) for c in worst if c.missing_pct > 0]))
            view.profiling = ProfilingSummary(
                tables=tables,
                coverage=[CoverageSummary(table=c.table, date_column=c.date_column, first_day=c.first_day,
                                          last_day=c.last_day, days=len(c.days)) for c in (coverage.tables if coverage else [])],
                anomalies=AnomalySummary(table=anomalies.table, model=anomalies.model,
                                         model_version=anomalies.model_version, features=anomalies.features,
                                         n_rows=anomalies.n_rows, n_anomalies=anomalies.n_anomalies,
                                         contamination=anomalies.params.get("contamination"))
                if anomalies else None)

        if cl := read(base, "cleaning.report"):
            view.cleaning = CleaningSummary(
                playbook=cl.playbook, rules=len(cl.applied),
                rules_with_effect=sum(1 for r in cl.applied if r.rows_affected),
                rows_changed=sum(r.rows_affected for r in cl.applied),
                applied=sorted(cl.applied, key=lambda r: -r.rows_affected),
                rows_before=cl.rows_before, rows_after=cl.rows_after)

        if manifest := read(base, "etl.manifest"):
            view.etl = EtlView(manifest=manifest, receipts=read(base, "etl.receipts"))

        view.request = read(run_id, "request.request")
        view.analysis = read(run_id, "analysis.result")

        if graph := read(base, "lineage.graph"):
            ref = view.analysis.kpi if view.analysis else None
            if ref is None and view.request is not None:
                ctx = context_for("analysis", base, runs_root, repo_root)
                if Path(ctx.inputs["catalog"]).exists():
                    catalog = load_yaml(KpiCatalog, ctx.inputs["catalog"])
                    ref = next((k.ref for k in catalog.kpis if k.name == view.request.metric), None)
            view.lineage = kpi_path(graph, ref) if ref else None
        return view

    @router.get("/runs/{run_id}/charts", response_model=DashboardView, tags=["pipeline"])
    def charts(run_id: RunId):
        """Samar's dashboard (dashboard_spec.json + chart_advice.json + the prepared data). The data is read
        from the run's own dashboard/ folder by FILE NAME only: the absolute paths of the spec are never used."""
        folder = runs_root / run_id / "dashboard"
        spec = read(run_id, "dashboard.spec")
        if spec is None:
            raise HTTPException(404, f"Run '{run_id}' has no dashboard yet.")
        advice_file = folder / "chart_advice.json"
        advice = json.loads(advice_file.read_text(encoding="utf-8")) if advice_file.exists() else {}
        ranking = {d["chart_id"]: d.get("candidates", []) for d in advice.get("decisions", [])}
        out = []
        for c in spec.charts:
            data = folder / Path(c.data_file.replace("\\", "/")).name
            rows = []
            if data.suffix == ".parquet" and data.exists():
                df = pd.read_parquet(data).head(200)
                rows = json.loads(df.to_json(orient="records", date_format="iso"))
            out.append(ChartView(chart_id=c.chart_id, chart_type=c.chart_type.value, title=c.title, x=c.x, y=c.y,
                                 color=c.color, reason=c.reason, rows=rows,
                                 alternatives=[ChartOption(chart_type=a["chart_type"], score=a["score"], eligible=a["eligible"],
                                                          reason=" ".join(a.get("reasons", []))) for a in ranking.get(c.chart_id, [])]))
        return DashboardView(title=spec.title, question=spec.question, kpi=spec.kpi, charts=out, warnings=spec.warnings,
                             comparison_shown=advice.get("comparison_shown"), rules_version=advice.get("rules_version"))

    # ---- Malek's request parser, live ----------------------------------------------------------------
    @router.post("/parse", response_model=ParsedQuestion, tags=["pipeline"])
    def parse(body: ParseQuestion):
        """Malek's agent (semantic.request) reads the question with the base run's glossary and KPI
        catalog and proposes metric, dimensions, periods. Only a PROPOSAL for the form: nothing is
        computed and its journal lines go to a temporary journal, thrown away. What counts is the
        request the user submits (POST /comparisons), which is journaled."""
        if not (runs_root / body.base_run).is_dir():
            raise HTTPException(404, f"Unknown run '{body.base_run}'.")
        from semantic.request import run as parse_request     # sentence-transformers is optional

        inputs = dict(context_for("request", body.base_run, runs_root, repo_root).inputs)
        with tempfile.TemporaryDirectory(prefix="biflow_parse_") as tmp:
            tmp = Path(tmp)
            inputs["upload"] = save(Upload(question=body.question, tables={}, uploaded_by="app"), tmp / "upload.json")
            ctx = RunContext(run_id="parse", agent="request", inputs=inputs, output_dir=tmp / "request",
                             journal=tmp / "journal.db")
            try:
                res = parse_request(ctx)
            except Exception as e:                                   # a proposal must never break the form
                return ParsedQuestion(status="failed", message=f"{type(e).__name__}: {e}"[:300])
            out = ctx.output("request")
            request = load(AnalysisRequest, out) if out.exists() else None
        status = {AgentStatus.SUCCESS: "success", AgentStatus.NEEDS_REVIEW: "needs_review"}.get(res.status, "failed")
        return ParsedQuestion(status=status, message=res.message or "", request=request)

    return router
