"""dag_runner.py — BIFlow pipeline DAG executor (Samar — BO1-01).

Design:
  - Uses graphlib.TopologicalSorter (stdlib) to resolve the execution order
    defined in contracts.pipeline.STEPS.
  - Runs ready tasks concurrently (ThreadPoolExecutor) with a configurable
    semaphore to cap parallelism.
  - Persists every task state in SQLite via task_store.py so runs can be
    resumed after a crash.
  - Imports each agent's run() function dynamically from its entrypoint string
    (e.g. "intake.column_types:run") — the orchestrator never imports
    agent internals directly.
  - Calls ctx.log() after each step so the audit journal is always current.
  - Streams progress via an optional callback (used by the Streamlit app).

Usage (CLI):
    python -m orchestrator.dag_runner --run-id run_001 --upload runs/run_001/upload/upload.json

Usage (Python):
    from orchestrator.dag_runner import run_pipeline
    result = run_pipeline("run_001", max_workers=4)
"""
from __future__ import annotations

import importlib
import logging
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Callable

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.audit import DEFAULT_JOURNAL
from contracts.pipeline import RUNS_ROOT, STEPS, context_for, graph, output_path

from orchestrator.task_store import (
    DEFAULT_DB,
    TaskStatus,
    get_run_summary,
    get_status,
    init_run,
    set_done,
    set_running,
)

log = logging.getLogger(__name__)


ProgressCallback = Callable[[str, str, str], None]
"""Signature: callback(step_name, status, message)."""


def _import_run(entrypoint: str) -> Callable[[RunContext], AgentResult]:
    """Dynamically import an agent's run() function from 'module:function'."""
    module_path, func_name = entrypoint.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def _execute_step(
    step_name: str,
    run_id: str,
    runs_root: Path,
    journal: Path,
    db: Path,
    params: dict,
    callback: ProgressCallback | None,
) -> AgentResult:
    """Run one pipeline step synchronously and record its state."""
    step_def = STEPS[step_name]
    ctx = context_for(step_name, run_id, runs_root=runs_root, journal=journal, params=params)

    set_running(run_id, step_name, db=db)
    if callback:
        callback(step_name, "RUNNING", f"Starting {step_name}…")

    try:
        agent_run = _import_run(step_def.entrypoint)
        result: AgentResult = agent_run(ctx)
    except ModuleNotFoundError as exc:
        # Agent not yet implemented — treat as SKIPPED
        msg = f"Agent not yet implemented: {exc}"
        log.warning("Step %s skipped — %s", step_name, msg)
        result = AgentResult(
            run_id=run_id, agent=step_name,
            status=AgentStatus.SKIPPED, message=msg,
        )
    except Exception as exc:
        msg = f"Unhandled error in {step_name}: {exc}"
        log.exception("Step %s failed", step_name)
        result = AgentResult(
            run_id=run_id, agent=step_name,
            status=AgentStatus.FAILED, message=msg,
        )

    task_status = {
        AgentStatus.SUCCESS:      TaskStatus.SUCCESS,
        AgentStatus.FAILED:       TaskStatus.FAILED,
        AgentStatus.NEEDS_REVIEW: TaskStatus.NEEDS_REVIEW,
        AgentStatus.SKIPPED:      TaskStatus.SKIPPED,
    }.get(result.status, TaskStatus.FAILED)

    set_done(run_id, step_name, task_status, result.message,
             {k: str(v) for k, v in result.outputs.items()}, db=db)

    if callback:
        callback(step_name, task_status.value, result.message)

    return result


def run_pipeline(
    run_id: str | None = None,
    *,
    max_workers: int = 4,
    runs_root: Path = RUNS_ROOT,
    journal: Path = DEFAULT_JOURNAL,
    db: Path = DEFAULT_DB,
    params: dict | None = None,
    stop_on_failure: bool = True,
    callback: ProgressCallback | None = None,
) -> dict[str, AgentResult]:
    """Execute the full BIFlow pipeline DAG.

    Args:
        run_id:          Unique identifier. Auto-generated if None.
        max_workers:     Maximum concurrent steps.
        runs_root:       Root folder for run outputs (default: runs/).
        journal:         Path to the SQLite audit journal.
        db:              Path to the SQLite task state store.
        params:          Extra params forwarded to every agent context.
        stop_on_failure: If True, skip all downstream steps after a FAILED step.
        callback:        Optional progress callback for the Streamlit UI.

    Returns:
        dict mapping step name → AgentResult.
    """
    if run_id is None:
        run_id = f"run_{uuid.uuid4().hex[:8]}"

    log.info("Starting pipeline run: %s", run_id)

    # Validate DAG — raises CycleError if there is a cycle
    dag = graph()
    try:
        TopologicalSorter(dag).static_order()  # validate only
    except CycleError as exc:
        raise RuntimeError(f"Pipeline DAG has a cycle: {exc}") from exc

    step_names = list(STEPS.keys())
    init_run(run_id, step_names, db=db)

    results: dict[str, AgentResult] = {}
    failed_steps: set[str] = set()
    paused_steps: set[str] = set()      # NEEDS_REVIEW, and every step that waits for it

    sorter = TopologicalSorter(dag)
    sorter.prepare()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures: dict[Future, str] = {}

        while sorter.is_active():
            # Submit all newly-ready steps (including any unblocked by skipped steps)
            newly_ready = list(sorter.get_ready())
            while newly_ready:
                for step_name in newly_ready:
                    # Resume support: skip steps already SUCCESS whose output files exist
                    step_def = STEPS[step_name]
                    prev_status = get_status(run_id, step_name, db=db)
                    if prev_status == TaskStatus.SUCCESS:
                        outputs_exist = (
                            all(
                                output_path(run_id, step_name, key, runs_root=runs_root).exists()
                                for key in step_def.outputs
                            )
                            if step_def.outputs
                            else True
                        )
                        if outputs_exist:
                            msg = f"Reused existing SUCCESS outputs from {run_id}"
                            log.info("Step %s already SUCCESS, skipping execution", step_name)
                            outputs = {
                                k: output_path(run_id, step_name, k, runs_root=runs_root)
                                for k in step_def.outputs
                            }
                            results[step_name] = AgentResult(
                                run_id=run_id,
                                agent=step_name,
                                status=AgentStatus.SUCCESS,
                                outputs=outputs,
                                message=msg,
                            )
                            if callback:
                                callback(step_name, TaskStatus.SUCCESS.value, msg)
                            sorter.done(step_name)
                            continue

                    # A dependency waits for a human (needs_review): this step cannot run yet.
                    # Resume the same run_id after the review: finished steps are reused.
                    waiting = STEPS[step_name].depends_on & paused_steps
                    if waiting:
                        msg = f"Waiting for the human review of: {', '.join(sorted(waiting))}"
                        log.info("Step %s: %s", step_name, msg)
                        set_done(run_id, step_name, TaskStatus.SKIPPED, msg, db=db)
                        results[step_name] = AgentResult(run_id=run_id, agent=step_name,
                                                         status=AgentStatus.SKIPPED, message=msg)
                        paused_steps.add(step_name)          # and so do the steps after it
                        if callback:
                            callback(step_name, "SKIPPED", msg)
                        sorter.done(step_name)
                        continue

                    # Check if any dependency failed
                    if stop_on_failure and any(
                        dep in failed_steps for dep in STEPS[step_name].depends_on
                    ):
                        msg = f"Skipped — upstream failure in: {STEPS[step_name].depends_on & failed_steps}"
                        log.warning("Skipping step %s: %s", step_name, msg)
                        set_done(run_id, step_name, TaskStatus.SKIPPED, msg, db=db)
                        results[step_name] = AgentResult(
                            run_id=run_id, agent=step_name,
                            status=AgentStatus.SKIPPED, message=msg,
                        )
                        if callback:
                            callback(step_name, "SKIPPED", msg)
                        sorter.done(step_name)
                        continue

                    future = pool.submit(
                        _execute_step,
                        step_name, run_id, runs_root, journal, db,
                        params or {}, callback,
                    )
                    futures[future] = step_name

                newly_ready = list(sorter.get_ready()) if sorter.is_active() else []

            if not futures:
                break   # nothing running and nothing ready → DAG complete

            # Wait for at least one step to finish before looping
            done_futures = []
            for future in list(futures.keys()):
                if future.done():
                    done_futures.append(future)

            if not done_futures:
                # Block on the next completion
                done_futures = [next(as_completed(futures))]

            for future in done_futures:
                step_name = futures.pop(future)
                result = future.result()
                results[step_name] = result
                if result.status == AgentStatus.FAILED:
                    failed_steps.add(step_name)
                elif result.status == AgentStatus.NEEDS_REVIEW:
                    paused_steps.add(step_name)
                sorter.done(step_name)

    log.info("Run %s complete. Steps: %d succeeded, %d failed, %d skipped.",
             run_id,
             sum(1 for r in results.values() if r.status == AgentStatus.SUCCESS),
             len(failed_steps),
             sum(1 for r in results.values() if r.status == AgentStatus.SKIPPED))

    return results


def get_run_status(run_id: str, db: Path = DEFAULT_DB) -> list[dict]:
    """Return the current state of all steps in a run (for the dashboard)."""
    return get_run_summary(run_id, db=db)


# ── CLI entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

    parser = argparse.ArgumentParser(description="BIFlow DAG runner")
    parser.add_argument("--run-id", default=None, help="Run identifier (auto if omitted)")
    parser.add_argument("--workers", type=int, default=4, help="Max parallel steps")
    args = parser.parse_args()

    def progress(step, status, msg):
        print(f"  [{status:>10}] {step}: {msg}")

    try:
        results = run_pipeline(
            run_id=args.run_id,
            max_workers=args.workers,
            callback=progress,
        )
        failed = [s for s, r in results.items() if r.status == AgentStatus.FAILED]
        if failed:
            print(f"\nFAILED steps: {failed}")
            sys.exit(1)
        print("\nAll steps completed.")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
