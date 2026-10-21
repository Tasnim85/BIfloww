"""tests/test_dag_runner.py — Tests for orchestrator DAG runner (Samar — Tâche 5).

Covers:
  - TaskStatus.NEEDS_REVIEW presence and behavior
  - AgentStatus.NEEDS_REVIEW mapping to TaskStatus.NEEDS_REVIEW
  - Propagation of NEEDS_REVIEW without marking step as FAILED
  - Resume-on-SUCCESS: skipping already successful steps whose outputs exist
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.agent import AgentResult, AgentStatus
from contracts.common import save
from contracts.intake import Upload
from contracts.pipeline import STEPS, output_path
from orchestrator.dag_runner import _execute_step, run_pipeline
from orchestrator.task_store import TaskStatus, get_status, init_run, set_done


def test_task_status_needs_review_enum():
    """TaskStatus enum must have NEEDS_REVIEW value."""
    assert hasattr(TaskStatus, "NEEDS_REVIEW")
    assert TaskStatus.NEEDS_REVIEW.value == "NEEDS_REVIEW"


def test_execute_step_needs_review(tmp_path):
    """When an agent returns NEEDS_REVIEW, the task must be recorded as NEEDS_REVIEW,
    not FAILED, and the callback receives 'NEEDS_REVIEW'."""
    db = tmp_path / "test_tasks.db"
    journal = tmp_path / "test_audit.db"
    runs_root = tmp_path / "runs"
    run_id = "test_run_nr"

    init_run(run_id, ["request"], db=db)

    callback_calls = []
    def callback(step, status, msg):
        callback_calls.append((step, status, msg))

    mock_result = AgentResult(
        run_id=run_id,
        agent="request",
        status=AgentStatus.NEEDS_REVIEW,
        message="Ambiguous question — needs human review",
    )

    with patch("orchestrator.dag_runner._import_run", return_value=lambda ctx: mock_result):
        result = _execute_step(
            step_name="request",
            run_id=run_id,
            runs_root=runs_root,
            journal=journal,
            db=db,
            params={},
            callback=callback,
        )

    assert result.status == AgentStatus.NEEDS_REVIEW
    recorded_status = get_status(run_id, "request", db=db)
    assert recorded_status == TaskStatus.NEEDS_REVIEW
    assert any(s == "NEEDS_REVIEW" for _, s, _ in callback_calls)


def test_resume_skips_success_with_existing_outputs(tmp_path):
    """On re-running a pipeline with existing run_id, steps already SUCCESS with
    existing output files are skipped, while non-success steps are executed."""
    db = tmp_path / "test_tasks.db"
    journal = tmp_path / "test_audit.db"
    runs_root = tmp_path / "runs"
    run_id = "test_run_resume"

    # Set up upload step as SUCCESS with its output files existing
    step_def = STEPS["upload"]
    init_run(run_id, list(STEPS.keys()), db=db)

    # Create dummy output files for 'upload' step
    upload_file = output_path(run_id, "upload", "upload", runs_root=runs_root)
    tables_dir = output_path(run_id, "upload", "tables", runs_root=runs_root)
    upload_file.parent.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    dummy_upload = Upload(question="test question", tables={})
    save(dummy_upload, upload_file)

    set_done(
        run_id,
        "upload",
        TaskStatus.SUCCESS,
        message="Upload succeeded previously",
        outputs={"upload": str(upload_file), "tables": str(tables_dir)},
        db=db,
    )

    executed_steps = []
    def mock_agent(ctx):
        executed_steps.append(ctx.agent)
        return AgentResult(
            run_id=ctx.run_id,
            agent=ctx.agent,
            status=AgentStatus.SUCCESS,
            message="OK",
        )

    # Run only down to upload and similarity
    with patch("orchestrator.dag_runner._import_run", return_value=mock_agent):
        results = run_pipeline(
            run_id=run_id,
            runs_root=runs_root,
            journal=journal,
            db=db,
            max_workers=1,
            stop_on_failure=True,
        )

    # 'upload' was already SUCCESS with outputs on disk -> must NOT have re-executed
    assert "upload" not in executed_steps
    assert results["upload"].status == AgentStatus.SUCCESS
    assert "Reused existing SUCCESS outputs" in results["upload"].message


def test_resume_retries_previously_failed_step(tmp_path):
    """If a step failed in a previous run, resuming must re-execute it."""
    db = tmp_path / "test_tasks.db"
    journal = tmp_path / "test_audit.db"
    runs_root = tmp_path / "runs"
    run_id = "test_run_retry"

    init_run(run_id, list(STEPS.keys()), db=db)

    # upload was SUCCESS with files
    upload_file = output_path(run_id, "upload", "upload", runs_root=runs_root)
    tables_dir = output_path(run_id, "upload", "tables", runs_root=runs_root)
    upload_file.parent.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    save(Upload(question="test", tables={}), upload_file)

    set_done(run_id, "upload", TaskStatus.SUCCESS, "OK", db=db)
    # similarity previously FAILED
    set_done(run_id, "similarity", TaskStatus.FAILED, "Network error", db=db)

    executed = []
    def mock_agent(ctx):
        executed.append(ctx.agent)
        return AgentResult(
            run_id=ctx.run_id,
            agent=ctx.agent,
            status=AgentStatus.SUCCESS,
            message="Now works",
        )

    with patch("orchestrator.dag_runner._import_run", return_value=mock_agent):
        results = run_pipeline(
            run_id=run_id,
            runs_root=runs_root,
            journal=journal,
            db=db,
            max_workers=1,
        )

    # 'upload' was skipped because it was SUCCESS with outputs
    assert "upload" not in executed
    # 'similarity' was FAILED previously -> must have been retried
    assert "similarity" in executed
