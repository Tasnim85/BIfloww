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
    max_retries: int = 1,
) -> AgentResult:
    """Run one pipeline step synchronously and record its state."""
    step_def = STEPS[step_name]
    ctx = context_for(step_name, run_id, runs_root=runs_root, journal=journal, params=params)

    set_running(run_id, step_name, db=db)
    if callback:
        callback(step_name, "RUNNING", f"Starting {step_name}…")

    # 1. Import phase: distinguish unbuilt agent from broken internal dependency
    try:
        agent_run = _import_run(step_def.entrypoint)
    except ModuleNotFoundError as exc:
        mod_name = step_def.entrypoint.rsplit(":", 1)[0]
        top_pkg = mod_name.split(".")[0]
        if exc.name in (mod_name, top_pkg):
            msg = f"Agent not yet implemented: {exc}"
            log.warning("Step %s skipped — %s", step_name, msg)
            result = AgentResult(
                run_id=run_id, agent=step_name,
                status=AgentStatus.SKIPPED, message=msg,
            )
        else:
            msg = f"Agent dependency missing for {step_name} ({exc.name}): {exc}"
            log.error("Step %s failed due to missing dependency — %s", step_name, msg)
            result = AgentResult(
                run_id=run_id, agent=step_name,
                status=AgentStatus.FAILED, message=msg,
            )
    except Exception as exc:
        msg = f"Unhandled error importing {step_name}: {exc}"
        log.exception("Step %s failed on import", step_name)
        result = AgentResult(
            run_id=run_id, agent=step_name,
            status=AgentStatus.FAILED, message=msg,
        )
    else:
        # 2. Execution phase with retry support
        attempt = 0
        last_exc: Exception | None = None
        result = None
        while attempt <= max_retries:
            try:
                result = agent_run(ctx)
                break
            except Exception as exc:
                last_exc = exc
                attempt += 1
                if attempt <= max_retries:
                    log.warning("Step %s failed on attempt %d/%d, retrying: %s",
                                step_name, attempt, max_retries, exc)

        if result is None:
            msg = f"Unhandled error in {step_name}: {last_exc}"
            log.exception("Step %s failed after %d attempts", step_name, max_retries + 1)
            result = AgentResult(
                run_id=run_id, agent=step_name,
                status=AgentStatus.FAILED, message=msg,
            )

        # 3. Output artifact validation: ensure SUCCESS actually produced declared outputs
        if result.status == AgentStatus.SUCCESS and step_def.outputs:
            missing_or_empty: list[str] = []
            for out_key in step_def.outputs:
                target_p = None
                if out_key in result.outputs:
                    val = result.outputs[out_key]
                    if isinstance(val, (str, Path)):
                        target_p = Path(val)
                if target_p is None or not target_p.exists():
                    target_p = Path(runs_root) / run_id / step_name / step_def.outputs[out_key]

                if not target_p.exists():
                    missing_or_empty.append(f"{out_key} (missing file)")
                elif target_p.is_file() and target_p.stat().st_size == 0:
                    missing_or_empty.append(f"{out_key} (empty file)")

            if missing_or_empty:
                msg = f"Step {step_name} declared SUCCESS without producing valid artifact(s): {', '.join(missing_or_empty)}"
                log.error(msg)
                result = AgentResult(
                    run_id=run_id, agent=step_name,
                    status=AgentStatus.FAILED, message=msg,
                    outputs=result.outputs,
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
    blocked_or_failed_steps: set[str] = set()

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

                    # Check if any dependency failed, was skipped, or requires human review
                    upstream_blocked = [
                        dep for dep in STEPS[step_name].depends_on
                        if dep in blocked_or_failed_steps
                    ]
                    if stop_on_failure and upstream_blocked:
                        needs_review_deps = [
                            d for d in upstream_blocked
                            if results.get(d) and results[d].status == AgentStatus.NEEDS_REVIEW
                        ]
                        failed_deps = [
                            d for d in upstream_blocked
                            if results.get(d) and results[d].status == AgentStatus.FAILED
                        ]
                        if needs_review_deps:
                            msg = f"Blocked — upstream step '{needs_review_deps[0]}' requires human review (NEEDS_REVIEW)"
                        elif failed_deps:
                            msg = f"Skipped — upstream failure in: {set(failed_deps)}"
                        else:
                            msg = f"Skipped — upstream dependency '{upstream_blocked[0]}' was not successful"

                        log.warning("Skipping step %s: %s", step_name, msg)
                        set_done(run_id, step_name, TaskStatus.SKIPPED, msg, db=db)
                        results[step_name] = AgentResult(
                            run_id=run_id, agent=step_name,
                            status=AgentStatus.SKIPPED, message=msg,
                        )
                        # Transitive skip: propagate blockage to all descendants
                        blocked_or_failed_steps.add(step_name)
                        failed_steps.add(step_name)

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
                if result.status != AgentStatus.SUCCESS:
                    blocked_or_failed_steps.add(step_name)
                if result.status == AgentStatus.FAILED:
                    failed_steps.add(step_name)
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
