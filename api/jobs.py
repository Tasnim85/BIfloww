"""Samar's part in the app: the user's OWN CSV files go through the whole DAG (orchestrator/dag_runner),
and the human reviews (PII, ETL, comparison) are answered from the app.

    POST /uploads                  files + question -> a new run up_<id>, started in the background
    GET  /runs/{run_id}/progress   status of the 13 steps, and the review waiting for the user (if any)
    POST /runs/{run_id}/review     the user approves / rejects the PII or ETL proposal -> the run resumes

The comparison review uses the existing route (POST /runs/{run_id}/comparison/decision): after the
decision, the run resumes here. The loop is the one of tools/integration/run_with_reviews.py.

Rules:
  * files: CSV only, safe names, size limits; stored in runs/<run_id>/incoming/ (runs/ is never committed);
  * decisions of the TEST DOUBLE (tools/integration/fake_ollama.py) go to runs/integration_journal.db,
    never to the real journal (runs/audit_journal.db);
  * the PII secret comes from the environment or .env (BO2_PII_SECRET, 32+ characters), never from the app;
  * every human decision is written in the journal before the run resumes.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.request import ProxyHandler, build_opener

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from contracts.audit import AuditEvent, log_event
from contracts.pipeline import STEPS

UPLOAD_RUN = re.compile(r"^up_[0-9a-f]{12}$")
MAX_FILES, MAX_FILE_MB, MAX_TOTAL_MB = 20, 150, 300
REVIEWABLE = ("pii", "cleaning", "etl")
# the types a person may give to a column the privacy agent is unsure about (privacy/detection.py, without UNKNOWN)
PII_TYPES = ["EMAIL", "PHONE", "PERSON_NAME", "PERSONAL_ID", "ADDRESS", "POSTAL_CODE", "COORDINATE", "BIRTH_DATE", "AGE",
             "SENSITIVE_ATTRIBUTE", "FREE_TEXT", "INTERNAL_KEY", "TIMESTAMP", "MEASURE", "CATEGORY"]


def is_upload_run(run_id: str) -> bool:
    return bool(UPLOAD_RUN.match(run_id))


def uses_test_double() -> bool:
    """fake_ollama answers /api/version with 'fake-test-double'; a real Ollama with its version number."""
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        with build_opener(ProxyHandler({})).open(f"{base}/api/version", timeout=3) as r:
            return "fake" in json.loads(r.read()).get("version", "")
    except (OSError, ValueError):
        return False


def local_llm_reachable() -> bool:
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        with build_opener(ProxyHandler({})).open(f"{base}/api/version", timeout=3):
            return True
    except OSError:
        return False


def safe_name(name: str) -> str | None:
    """'Ventes 2024 (v2).csv' -> 'Ventes_2024_v2.csv'; anything that is not a .csv -> None."""
    base = Path(name.replace("\\", "/")).name
    if not base.lower().endswith(".csv"):
        return None
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", base[:-4]).strip("_")[:80]
    return f"{stem}.csv" if stem else None


def write_approval(path: Path, data: dict) -> None:
    """Who approved what, and when, next to the agent's outputs (same idea as Ikbel's approval.json)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---- response models ---------------------------------------------------------------------------------------
class StepProgress(BaseModel):
    step: str
    status: str                        # PENDING, RUNNING, SUCCESS, NEEDS_REVIEW, FAILED, SKIPPED
    message: str = ""


class PiiQuestion(BaseModel):
    table: str
    column: str
    proposed: str                      # the type llama3 proposed
    confidence: float | None = None


class EtlTable(BaseModel):
    source: str                        # the uploaded table
    role: str                          # fact / dimension
    grain: str
    measures: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)


class EtlLink(BaseModel):
    child: str
    parent: str
    columns: list[str]
    kept: bool


class CleaningRule(BaseModel):
    table: str
    column: str
    action: str                        # trim, numeric, datetime, fill_constant
    value: str | float | int | None = None


class Review(BaseModel):
    step: Literal["pii", "cleaning", "etl", "comparisons", "other"]
    message: str
    approvable: bool = True            # False: the app can only stop the run (e.g. critical values to fix in the data)
    pii: list[PiiQuestion] = Field(default_factory=list)
    pii_types: list[str] = Field(default_factory=lambda: list(PII_TYPES))   # the choices offered to the person
    rules: list[CleaningRule] = Field(default_factory=list)   # cleaning rules proposed by llama3 (no playbook fits)
    schema_type: str | None = None
    tables: list[EtlTable] = Field(default_factory=list)
    links: list[EtlLink] = Field(default_factory=list)


class Progress(BaseModel):
    run_id: str
    state: Literal["running", "needs_review", "done", "failed", "stopped"]
    steps: list[StepProgress]
    review: Review | None = None
    error: str | None = None
    test_double: bool = False          # decisions made by fake_ollama (separate journal)


class UploadStarted(BaseModel):
    run_id: str
    tables: list[str]


class ReviewAnswer(BaseModel):
    step: Literal["pii", "cleaning", "etl"]
    decision: Literal["approve", "reject"]
    reviewer: str = Field(..., min_length=1, max_length=100,
                          description="Who decides: set by the web server from the signed-in user, never typed")
    pii_types: dict[str, str] = Field(default_factory=dict, max_length=200,
                                      description="PII review: 'table.column' -> the type the person chose (default: the proposal)")


# ---- the jobs ------------------------------------------------------------------------------------------------
class Jobs:
    """Background runs of the DAG. State is on disk (runs/<id>/job.json + the task store), so the API can
    restart: a run waiting for a review just waits; a run that was running is shown as stopped."""

    def __init__(self, runs_root: Path, repo_root: Path, max_running: int = 2):
        self.runs_root, self.repo_root, self.max_running = Path(runs_root), Path(repo_root), max_running
        self.db = self.runs_root / "task_store.db"
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()

    # -- files on disk
    def job_file(self, run_id: str) -> Path:
        return self.runs_root / run_id / "job.json"

    def job(self, run_id: str) -> dict:
        f = self.job_file(run_id)
        if not is_upload_run(run_id) or not f.exists():
            raise HTTPException(404, f"Unknown upload run '{run_id}'.")
        return json.loads(f.read_text(encoding="utf-8"))

    def save_job(self, run_id: str, job: dict) -> None:
        self.job_file(run_id).write_text(json.dumps(job, indent=1), encoding="utf-8")

    def journal(self, job: dict) -> Path:
        return self.runs_root / job["journal"]

    def running(self, run_id: str) -> bool:
        t = self.threads.get(run_id)
        return bool(t and t.is_alive())

    # -- start
    def start(self, files: list[tuple[str, bytes]], question: str, uploaded_by: str, lang: str) -> UploadStarted:
        secret = os.environ.get("BO2_PII_SECRET", "")
        if len(secret) < 32:
            raise HTTPException(503, "BO2_PII_SECRET is not set (32+ characters) in the environment or .env.")
        if not local_llm_reachable():
            raise HTTPException(503, "No local LLM: start Ollama with llama3 (or tools/integration/fake_ollama.py for tests).")
        with self.lock:
            if sum(self.running(r) for r in list(self.threads)) >= self.max_running:
                raise HTTPException(429, "Too many pipelines running: try again in a few minutes.")
            run_id = f"up_{uuid.uuid4().hex[:12]}"
            incoming = self.runs_root / run_id / "incoming"
            incoming.mkdir(parents=True)
            names = []
            for name, data in files:
                (incoming / name).write_bytes(data)
                names.append(name[:-4])
            test_double = uses_test_double()
            job = {"run_id": run_id, "question": question, "uploaded_by": uploaded_by, "lang": lang,
                   "journal": "integration_journal.db" if test_double else "audit_journal.db", "test_double": test_double,
                   "params": {"pii_overrides": {}, "etl_approval": None}, "rejected": None, "error": None}
            self.save_job(run_id, job)
            self._launch(run_id)
        return UploadStarted(run_id=run_id, tables=names)

    def _params(self, job: dict) -> dict:
        p = {"source_dir": str(self.runs_root / job["run_id"] / "incoming"), "question": job["question"],
             "uploaded_by": job["uploaded_by"], "lang": job["lang"], "language": job["lang"], "backend": "json",
             "playbook": str(self.repo_root / "cleaning/playbooks/playbook_v2.0.json"),
             # a playbook approved in the app stays with its run: the team decides what enters cleaning/playbooks/
             "playbook_dir": str(self.runs_root / job["run_id"] / "cleaning_playbooks")}
        if os.environ.get("BIFLOW_CLEANING_MODE") == "generate":
            # demo / test switch: no playbook, llama3 proposes the cleaning rules and a person approves them in the app
            p.pop("playbook")
            p["playbook_mode"] = "generate"
        if job["params"].get("pii_overrides"):
            p["pii_overrides"] = job["params"]["pii_overrides"]
        if job["params"].get("etl_approval"):
            p["etl_approval"] = job["params"]["etl_approval"]
        if job["params"].get("cleaning_approval"):
            p["cleaning_proposal"] = job["params"]["cleaning_proposal"]
            p["cleaning_approval"] = job["params"]["cleaning_approval"]
        return p

    def _launch(self, run_id: str) -> None:
        from orchestrator.dag_runner import run_pipeline        # Samar's orchestrator

        def work():
            job = self.job(run_id)
            try:
                run_pipeline(run_id=run_id, runs_root=self.runs_root, journal=self.journal(job), db=self.db,
                             params=self._params(job))
            except Exception as e:                                # shown to the user, never hidden
                job = self.job(run_id)
                job["error"] = f"{type(e).__name__}: {e}"[:500]
                self.save_job(run_id, job)

        t = threading.Thread(target=work, name=f"pipeline-{run_id}", daemon=True)
        self.threads[run_id] = t
        t.start()

    # -- read
    def progress(self, run_id: str) -> Progress:
        job = self.job(run_id)
        from orchestrator.task_store import get_run_summary
        rows = {r["step"]: r for r in get_run_summary(run_id, db=self.db)} if self.db.exists() else {}
        steps = [StepProgress(step=s, status=str(rows.get(s, {}).get("status") or "PENDING"),
                              message=str(rows.get(s, {}).get("message") or "")[:300]) for s in STEPS]
        status = {s.step: s.status for s in steps}
        review = None
        if self.running(run_id):
            state = "running"
        elif job.get("rejected"):
            state = "stopped"
        elif job.get("error"):
            state = "failed"
        elif waiting := [s for s in STEPS if status[s] == "NEEDS_REVIEW"]:
            state, review = "needs_review", self.review_of(run_id, waiting[0], status_message=rows[waiting[0]].get("message"))
        elif all(v == "SUCCESS" for v in status.values()):
            state = "done"
        elif any(v == "FAILED" for v in status.values()):
            state = "failed"
        else:
            state = "stopped"                                      # e.g. the API restarted during the run
        return Progress(run_id=run_id, state=state, steps=steps, review=review, test_double=job["test_double"],
                        error=job.get("error") or (f"Rejected by the reviewer at step {job['rejected']}." if job.get("rejected") else None))

    def review_of(self, run_id: str, step: str, status_message: str | None) -> Review:
        """What the user must decide, built from the agent's files (no local path is returned)."""
        msg = str(status_message or "")[:400]
        run = self.runs_root / run_id
        if step == "pii":
            report = json.loads((run / "pii" / "pii_report.bo2.json").read_text(encoding="utf-8"))
            kinds = {(c["table"], c["column"]): c for c in report.get("classification", [])}
            questions = [PiiQuestion(table=i["table"], column=i["column"],
                                     proposed=kinds.get((i["table"], i["column"]), {}).get("semantic_type", "UNKNOWN"),
                                     confidence=kinds.get((i["table"], i["column"]), {}).get("confidence"))
                         for i in report.get("needs_review", [])]
            return Review(step="pii", message=msg, pii=questions)
        if step == "etl":
            env = json.loads((run / "etl" / "warehouse_proposal.json").read_text(encoding="utf-8"))
            src = {t: info.get("source", t) for t, info in env.get("tables", {}).items()}
            design = env.get("design", {})
            kept = set(design.get("relationships", []))
            return Review(step="etl", message=msg, schema_type=design.get("schema_type"),
                          tables=[EtlTable(source=src.get(t["table"], t["table"]), role=t.get("role", "?"), grain=t.get("grain", ""),
                                           measures=t.get("measures", []), dates=t.get("dates", []))
                                  for t in design.get("tables", [])],
                          links=[EtlLink(child=src.get(c["child"], c["child"]), parent=src.get(c["parent"], c["parent"]),
                                         columns=c.get("columns", []), kept=c["id"] in kept) for c in env.get("candidates", [])])
        if step == "cleaning":
            proposal = run / "cleaning" / "proposed_rules.json"
            if proposal.exists():                      # llama3 proposed rules: a human must approve them
                data = json.loads(proposal.read_text(encoding="utf-8"))
                return Review(step="cleaning", message=msg, rules=[CleaningRule(**r) for r in data.get("rules", [])])
            return Review(step="cleaning", message=msg, approvable=False)   # data to fix at the source
        if step == "comparisons":
            return Review(step="comparisons", message=msg)
        return Review(step="other", message=msg, approvable=False)

    # -- write
    def answer(self, run_id: str, a: ReviewAnswer) -> Progress:
        job = self.job(run_id)
        prog = self.progress(run_id)
        if prog.state != "needs_review" or prog.review is None or prog.review.step != a.step:
            raise HTTPException(409, f"Run '{run_id}' is not waiting for a review of '{a.step}'.")
        run = self.runs_root / run_id
        approved_at = datetime.now(timezone.utc).isoformat()
        evidence: dict = {"reviewer": a.reviewer, "approved_at": approved_at}
        if a.decision == "reject":
            job["rejected"] = a.step
        elif not prog.review.approvable:
            raise HTTPException(409, "This review cannot be approved in the app: the data must be fixed at the source.")
        elif a.step == "pii":
            answers = {f"{q.table}.{q.column}": a.pii_types.get(f"{q.table}.{q.column}", q.proposed) for q in prog.review.pii}
            unsure = [k for k, v in answers.items() if v not in PII_TYPES]
            if unsure:      # 'UNKNOWN' (or anything else) is not an answer: the person must choose a type
                raise HTTPException(400, f"Choose a type for: {', '.join(unsure)}. Allowed: {', '.join(PII_TYPES)}")
            job["params"]["pii_overrides"] = {**job["params"].get("pii_overrides", {}), **answers}
            evidence["pii_overrides"] = answers
            write_approval(run / "pii" / "approval.json", {"answers": answers, **evidence})
        elif a.step == "cleaning":                # Ikbel's format: proposal sha256 + reviewer + approved_at
            from cleaning.llm_rules import approve
            proposal = run / "cleaning" / "proposed_rules.json"
            approval = approve(proposal, a.reviewer, run / "cleaning" / "approval.json")
            job["params"]["cleaning_proposal"], job["params"]["cleaning_approval"] = str(proposal), str(approval)
            evidence.update(json.loads(approval.read_text(encoding="utf-8")))
        else:                                     # Ahmed's ETL only needs the sha256; the person and time are kept too
            proposal = run / "etl" / "warehouse_proposal.json"
            job["params"]["etl_approval"] = evidence["proposal_sha256"] = hashlib.sha256(proposal.read_bytes()).hexdigest()
            write_approval(run / "etl" / "approval.json", evidence)
        log_event(AuditEvent(run_id=run_id, agent=a.step, step="human_review",
                             decision=("APPROVED" if a.decision == "approve" else "REJECTED") + f" by {a.reviewer}",
                             rule_version="app-review@1.0", evidence=evidence), self.journal(job))
        self.save_job(run_id, job)
        if a.decision == "approve":
            self.resume(run_id)
        return self.progress(run_id)

    def resume(self, run_id: str) -> None:
        """Run the DAG again on the SAME run id: finished steps are reused (orchestrator resume)."""
        with self.lock:
            if not self.running(run_id):
                self._launch(run_id)


def make_jobs_router(jobs: Jobs) -> APIRouter:
    router = APIRouter()

    @router.post("/uploads", response_model=UploadStarted, tags=["pipeline"])
    async def upload(files: list[UploadFile] = File(..., description="CSV files"),
                     question: str = Form(..., min_length=3, max_length=500),
                     uploaded_by: str = Form("app user", max_length=100),
                     lang: Literal["fr", "en"] = Form("en")):
        """Samar's intake: the user's CSV files and question run through the whole DAG, in the background."""
        if not 1 <= len(files) <= MAX_FILES:
            raise HTTPException(400, f"Send between 1 and {MAX_FILES} CSV files.")
        out, seen, total = [], set(), 0
        for f in files:
            name = safe_name(f.filename or "")
            if name is None:
                raise HTTPException(400, f"'{f.filename}' is not a .csv file.")
            if name.lower() in seen:
                raise HTTPException(400, f"Two files are named '{name}'.")
            data = await f.read(MAX_FILE_MB * 1024 * 1024 + 1)
            if len(data) > MAX_FILE_MB * 1024 * 1024:
                raise HTTPException(413, f"'{name}' is larger than {MAX_FILE_MB} MB.")
            total += len(data)
            if total > MAX_TOTAL_MB * 1024 * 1024:
                raise HTTPException(413, f"The files are larger than {MAX_TOTAL_MB} MB in total.")
            if not data.strip():
                raise HTTPException(400, f"'{name}' is empty.")
            seen.add(name.lower())
            out.append((name, data))
        return jobs.start(out, question.strip(), uploaded_by, lang)

    @router.get("/runs/{run_id}/progress", response_model=Progress, tags=["pipeline"])
    def progress(run_id: str):
        if not is_upload_run(run_id):
            raise HTTPException(404, "Only uploaded runs (up_...) have a progress.")
        return jobs.progress(run_id)

    @router.post("/runs/{run_id}/review", response_model=Progress, tags=["pipeline"])
    def review(run_id: str, body: ReviewAnswer):
        """The user's answer to the PII or ETL review, written in the journal; the run resumes."""
        if not is_upload_run(run_id):
            raise HTTPException(404, "Only uploaded runs (up_...) have reviews.")
        return jobs.answer(run_id, body)

    return router
