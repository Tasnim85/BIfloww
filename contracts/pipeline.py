"""Contract 3b: the DAG. Which step reads what, and under which FILE NAME it writes.

This is the glue between everyone. Because file names are fixed here, every path
of a run is known in advance:  runs/<run_id>/<step>/<file name>.
So anyone can build their RunContext alone with context_for() and drop a
hand-made input file at that path to test without waiting for the others.

Input reference formats:
    "<step>.<output key>"     an output of another step, e.g. "etl.warehouse"
    "static:<path>"           a file versioned in the repo, e.g. "static:kpi/catalog.yaml"
"""
from graphlib import TopologicalSorter
from pathlib import Path

from pydantic import Field

from contracts.agent import RunContext
from contracts.audit import DEFAULT_JOURNAL
from contracts.common import AgentName, Contract

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = Path("runs")


class Step(Contract):
    name: AgentName
    owner: str
    entrypoint: str                     # "module:function" the orchestrator calls
    inputs: dict[str, str] = Field(default_factory=dict)   # input key -> reference
    outputs: dict[str, str] = Field(default_factory=dict)  # output key -> file/folder name
    after: list[AgentName] = Field(default_factory=list)   # extra ordering, no file passed

    @property
    def depends_on(self) -> set[str]:
        deps = {ref.split(".")[0] for ref in self.inputs.values() if not ref.startswith("static:")}
        return deps | {a.value for a in self.after}


_STEPS = [
    Step(name=AgentName.UPLOAD, owner="Samar", entrypoint="app.upload:run",
         outputs={"upload": "upload.json", "tables": "tables/"}),

    Step(name=AgentName.SIMILARITY, owner="Malek", entrypoint="intake.similarity:run",
         inputs={"upload": "upload.upload", "tables": "upload.tables"},
         outputs={"report": "similarity_report.json"}),

    Step(name=AgentName.COLUMN_TYPES, owner="Malek", entrypoint="intake.column_types:run",
         inputs={"tables": "upload.tables"},
         outputs={"report": "column_types.json"}),

    Step(name=AgentName.PII, owner="Ikbel", entrypoint="privacy.pii:run",
         inputs={"tables": "upload.tables", "column_types": "column_types.report"},
         outputs={"report": "pii_report.json", "tables": "tables/"}),

    Step(name=AgentName.PROFILING, owner="Ahmed", entrypoint="profiling.profiler:run",
         inputs={"tables": "pii.tables", "column_types": "column_types.report"},
         outputs={"profile": "profile_report.json", "anomalies": "anomaly_report.json",
                  "model": "anomaly_model.joblib", "scores": "anomaly_scores.parquet"}),

    Step(name=AgentName.CLEANING, owner="Ikbel", entrypoint="cleaning.cleaner:run",
         inputs={"tables": "pii.tables", "profile": "profiling.profile",
                 "similarity": "similarity.report", "column_types": "column_types.report",
                 "playbooks": "static:cleaning/playbooks"},
         outputs={"report": "cleaning_report.json", "tables": "tables/"}),

    Step(name=AgentName.ETL, owner="Ahmed", entrypoint="etl.build:run",
         inputs={"tables": "cleaning.tables"},
         outputs={"warehouse": "warehouse.duckdb", "manifest": "warehouse_manifest.json",
                  "receipts": "receipts.json"}),

    Step(name=AgentName.REQUEST, owner="Malek", entrypoint="semantic.request:run",
         inputs={"upload": "upload.upload", "glossary": "static:semantic/glossary.yaml",
                 "catalog": "static:kpi/catalog.yaml"},
         outputs={"request": "analysis_request.json"}),

    Step(name=AgentName.ANALYSIS, owner="Rabeb", entrypoint="analysis.analyst:run",
         inputs={"request": "request.request", "warehouse": "etl.warehouse",
                 "manifest": "etl.manifest", "receipts": "etl.receipts",
                 "catalog": "static:kpi/catalog.yaml"},
         outputs={"result": "analysis_result.json", "data": "result.parquet"}),

    Step(name=AgentName.COMPARISONS, owner="Tasnim", entrypoint="comparisons.checker:run",
         inputs={"request": "request.request", "result": "analysis.result",
                 "warehouse": "etl.warehouse", "manifest": "etl.manifest",
                 "receipts": "etl.receipts", "catalog": "static:kpi/catalog.yaml"},
         outputs={"report": "comparison_report.json"}),

    Step(name=AgentName.DASHBOARD, owner="Samar", entrypoint="app.dashboard:run",
         inputs={"request": "request.request", "result": "analysis.result",
                 "data": "analysis.data", "comparisons": "comparisons.report"},
         outputs={"spec": "dashboard_spec.json"}),

    Step(name=AgentName.LINEAGE, owner="Ahmed", entrypoint="etl.lineage:run",
         inputs={"receipts": "etl.receipts", "manifest": "etl.manifest",
                 "catalog": "static:kpi/catalog.yaml"},
         outputs={"graph": "lineage.json"}),

    Step(name=AgentName.AUDITOR, owner="Tasnim", entrypoint="auditor.agent:run",
         inputs={"anomalies": "profiling.anomalies", "model": "profiling.model",
                 "scores": "profiling.scores", "lineage": "lineage.graph"},
         outputs={"explanations": "explanations.json", "drift": "drift_report.json",
                  "integrity": "integrity_report.json"},
         after=[AgentName.DASHBOARD]),     # runs last: the whole run is in the journal
]

STEPS: dict[str, Step] = {s.name.value: s for s in _STEPS}


def graph() -> dict[str, set[str]]:
    """{step: steps it waits for}. Feed it to graphlib.TopologicalSorter."""
    return {name: s.depends_on for name, s in STEPS.items()}


def execution_order() -> list[str]:
    """One valid order. Raises graphlib.CycleError if the DAG has a cycle."""
    return list(TopologicalSorter(graph()).static_order())


def output_path(run_id: str, step: str, key: str, runs_root: Path = RUNS_ROOT) -> Path:
    return Path(runs_root) / run_id / step / STEPS[step].outputs[key]


def resolve(ref: str, run_id: str, runs_root: Path = RUNS_ROOT,
            repo_root: Path = REPO_ROOT) -> Path:
    """Turn an input reference into a real path."""
    if ref.startswith("static:"):
        return Path(repo_root) / ref.removeprefix("static:")
    step, key = ref.split(".", 1)
    return output_path(run_id, step, key, runs_root)


def context_for(step: str, run_id: str, runs_root: Path = RUNS_ROOT,
                repo_root: Path = REPO_ROOT, journal: Path = DEFAULT_JOURNAL,
                params: dict | None = None) -> RunContext:
    """The exact RunContext the orchestrator will give to `step`. Use it in your tests."""
    s = STEPS[step]
    return RunContext(
        run_id=run_id, agent=step,
        inputs={k: resolve(ref, run_id, runs_root, repo_root) for k, ref in s.inputs.items()},
        output_dir=Path(runs_root) / run_id / step,
        params=params or {}, journal=journal,
    )
