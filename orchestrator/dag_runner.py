"""dag_runner.py — BIFlow pipeline DAG executor (Samar — BO1-01).

Hardened multi-agent DAG runner:
  - graphlib.TopologicalSorter static & dynamic dependency resolution.
  - Concurrency capped with ThreadPoolExecutor.
  - Strict dependency barriers: FAILED, NEEDS_REVIEW, and SKIPPED propagate transitively.
  - stop_on_failure=False allows independent disjoint branches to run while strictly
    blocking any step that depends on a failed or review-pending step.
  - Centralized artifact integrity & contract checks via validate_step_artifacts:
    canonical path in-run, non-empty, file-vs-dir, JSON Pydantic contracts,
    real Parquet readability via pyarrow, DuckDB table checks.
  - Safe resumption: requires all upstream dependencies to be SUCCESS and unbroken,
    invalidates downstream when upstream re-executes or changes, verifies all outputs
    pass contract checks before reusing cached results.
  - Selective retry policy: retries only transient I/O / network failures,
    never retries deterministic code bugs or missing input files.
  - Full audit logging: logs all resumptions and invalidations in the SQLite journal.
  - Loads local secrets from .env via bo2.config.load_local().
"""
from __future__ import annotations

import importlib
import json
import logging
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Callable

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.audit import DEFAULT_JOURNAL, AuditEvent, log_event
from contracts.pipeline import RUNS_ROOT, STEPS, context_for, graph, output_path
from orchestrator.artifact_validator import validate_step_artifacts

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

# Load project-local configuration/secrets if available
try:
    from bo2.config import load_local
    load_local()
except Exception:
    pass

TRANSIENT_ERRORS = (TimeoutError, ConnectionError)


def _is_transient_error(exc: Exception) -> bool:
    """Determine if an exception is retriable (transient I/O, network) or deterministic."""
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError, FileNotFoundError,
                        IsADirectoryError, NotADirectoryError, PermissionError, json.JSONDecodeError)):
        return False
    if isinstance(exc, TRANSIENT_ERRORS):
        return True
    if isinstance(exc, OSError):
        # Retry only transient network/timeout socket errnos
        if getattr(exc, "errno", None) in {11, 35, 110, 10053, 10054, 10060}:
            return True
    return False


ProgressCallback = Callable[[str, str, str], None]
"""Signature: callback(step_name, status, message)."""


def _import_run(entrypoint: str) -> Callable[[RunContext], AgentResult]:
    """Dynamically import an agent's run() function from 'module:function'."""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    module_path, func_name = entrypoint.rsplit(":", 1)
    if module_path.startswith("app.") and "app" in sys.modules:
        if not hasattr(sys.modules["app"], "__path__"):
            sys.modules["app"].__path__ = [str(repo_root / "app")]

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
    retry_delay: float = 0.0,
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
        # 2. Execution phase with selective retry for transient errors
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
                if attempt <= max_retries and _is_transient_error(exc):
                    log.warning("Step %s encountered transient error on attempt %d/%d, retrying: %s",
                                step_name, attempt, max_retries, exc)
                    if retry_delay > 0:
                        time.sleep(retry_delay)
                else:
                    # Non-transient or retries exhausted
                    log.error("Step %s failed with non-retriable exception: %s", step_name, exc)
                    break

        if result is None:
            msg = f"Unhandled error in {step_name}: {last_exc}"
            log.exception("Step %s failed after %d attempts", step_name, attempt)
            result = AgentResult(
                run_id=run_id, agent=step_name,
                status=AgentStatus.FAILED, message=msg,
            )

        # 3. Output artifact validation: ensure SUCCESS actually produced declared outputs
        if result.status == AgentStatus.SUCCESS and step_def.outputs:
            missing_or_invalid = validate_step_artifacts(
                step_name=step_name,
                run_id=run_id,
                declared_outputs=step_def.outputs,
                actual_outputs=result.outputs,
                runs_root=runs_root,
            )
            if missing_or_invalid:
                msg = f"Step {step_name} declared SUCCESS without producing valid artifact(s): {', '.join(missing_or_invalid)}"
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
    max_retries: int = 1,
    retry_delay: float = 0.0,
    approved_reviews: dict | None = None,
    callback: ProgressCallback | None = None,
) -> dict[str, AgentResult]:
    """Execute the full BIFlow pipeline DAG.

    Args:
        run_id:           Unique identifier. Auto-generated if None.
        max_workers:      Maximum concurrent steps.
        runs_root:        Root folder for run outputs (default: runs/).
        journal:          Path to the SQLite audit journal.
        db:               Path to the SQLite task state store.
        params:           Extra params forwarded to every agent context.
        stop_on_failure:  If True, abort independent branches on any failure.
                          Regardless of stop_on_failure, direct/transitive
                          dependents of failed/blocked tasks are ALWAYS blocked.
        max_retries:      Number of retries for transient errors.
        retry_delay:      Delay in seconds between retries.
        approved_reviews: Dict of human approval decisions for review-pending steps.
        callback:         Optional progress callback for UI/CLI.

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
    review_origins: dict[str, set[str]] = {}
    reused_steps: set[str] = set()
    approved_steps = approved_reviews or (params.get("approved_reviews") if params else None) or {}

    sorter = TopologicalSorter(dag)
    sorter.prepare()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures: dict[Future, str] = {}

        while sorter.is_active():
            newly_ready = list(sorter.get_ready())
            while newly_ready:
                for step_name in newly_ready:
                    step_def = STEPS[step_name]
                    prev_status = get_status(run_id, step_name, db=db)

                    # Human review approval check: if previous run was NEEDS_REVIEW and is approved
                    if prev_status == TaskStatus.NEEDS_REVIEW and step_name in approved_steps:
                        approval = approved_steps[step_name]
                        if approval.get("decision") == "APPROVED":
                            log.info("Human review approved for step %s by %s", step_name, approval.get("reviewer", "human"))
                            # Unblock step so it can be re-run or accepted

                    # Resume support: skip steps already SUCCESS whose dependencies are SUCCESS
                    upstream_deps = step_def.depends_on
                    dependencies_successful = all(
                        dep in results and results[dep].status == AgentStatus.SUCCESS
                        for dep in upstream_deps
                    )
                    upstream_reused = all(
                        dep in reused_steps
                        for dep in upstream_deps
                    )

                    if prev_status == TaskStatus.SUCCESS and dependencies_successful and upstream_reused:
                        missing_or_invalid = validate_step_artifacts(
                            step_name=step_name,
                            run_id=run_id,
                            declared_outputs=step_def.outputs,
                            runs_root=runs_root,
                        )
                        if not missing_or_invalid:
                            msg = f"Reused existing SUCCESS outputs from {run_id}"
                            log.info("Step %s already SUCCESS with valid outputs, skipping execution", step_name)
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
                            reused_steps.add(step_name)
                            try:
                                log_event(AuditEvent(
                                    run_id=run_id,
                                    agent=step_name,
                                    step="resumption",
                                    decision="REUSED",
                                    evidence={"outputs": [str(p) for p in outputs.values()]}
                                ), journal=journal)
                            except Exception:
                                pass
                            if callback:
                                callback(step_name, TaskStatus.SUCCESS.value, msg)
                            sorter.done(step_name)
                            continue
                        else:
                            inval_msg = f"Corrupted or invalid outputs: {', '.join(missing_or_invalid)}"
                            log.warning("Invalidating cached SUCCESS for step %s: %s", step_name, inval_msg)
                            try:
                                log_event(AuditEvent(
                                    run_id=run_id,
                                    agent=step_name,
                                    step="invalidation",
                                    decision="INVALIDATED",
                                    evidence={"reason": inval_msg}
                                ), journal=journal)
                            except Exception:
                                pass
                    elif prev_status == TaskStatus.SUCCESS and not dependencies_successful and upstream_deps:
                        inval_msg = "Upstream dependencies not in SUCCESS status"
                        log.warning("Invalidating cached SUCCESS for step %s: %s", step_name, inval_msg)
                        try:
                            log_event(AuditEvent(
                                run_id=run_id,
                                agent=step_name,
                                step="invalidation",
                                decision="INVALIDATED",
                                evidence={"reason": inval_msg}
                            ), journal=journal)
                        except Exception:
                            pass
                    elif prev_status == TaskStatus.SUCCESS and not upstream_reused and upstream_deps:
                        inval_msg = "Upstream dependencies re-executed; invalidating cached outputs"
                        log.info("Step %s: %s", step_name, inval_msg)
                        try:
                            log_event(AuditEvent(
                                run_id=run_id,
                                agent=step_name,
                                step="invalidation",
                                decision="INVALIDATED",
                                evidence={"reason": inval_msg}
                            ), journal=journal)
                        except Exception:
                            pass

                    # Dependency Barrier: check if ANY upstream dependency failed, was skipped, or is in review
                    upstream_blocked = [
                        dep for dep in step_def.depends_on
                        if dep in blocked_or_failed_steps
                    ]
                    # Upstream blockage ALWAYS blocks dependent step, regardless of stop_on_failure!
                    if upstream_blocked:
                        # Check if blocked due to a pending human review (direct or inherited)
                        review_sources = set()
                        for d in upstream_blocked:
                            if d in review_origins:
                                review_sources.update(review_origins[d])
                            elif results.get(d) and results[d].status == AgentStatus.NEEDS_REVIEW:
                                review_sources.add(d)

                        failed_deps = [
                            d for d in upstream_blocked
                            if results.get(d) and results[d].status == AgentStatus.FAILED
                        ]

                        if review_sources:
                            msg = f"Waiting for the human review of: {', '.join(sorted(review_sources))}"
                            review_origins[step_name] = review_sources
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
                        # Transitive propagation: mark this step blocked as well
                        blocked_or_failed_steps.add(step_name)
                        failed_steps.add(step_name)

                        if callback:
                            callback(step_name, "SKIPPED", msg)
                        sorter.done(step_name)
                        continue

                    # If stop_on_failure is enabled and ANY failure occurred anywhere, abort independent branches
                    if stop_on_failure and failed_steps:
                        msg = f"Aborted — stop_on_failure=True and failure exists in DAG: {set(failed_steps)}"
                        log.warning("Aborting step %s: %s", step_name, msg)
                        set_done(run_id, step_name, TaskStatus.SKIPPED, msg, db=db)
                        results[step_name] = AgentResult(
                            run_id=run_id, agent=step_name,
                            status=AgentStatus.SKIPPED, message=msg,
                        )
                        blocked_or_failed_steps.add(step_name)
                        failed_steps.add(step_name)

                        if callback:
                            callback(step_name, "SKIPPED", msg)
                        sorter.done(step_name)
                        continue

                    future = pool.submit(
                        _execute_step,
                        step_name, run_id, runs_root, journal, db,
                        params or {}, callback, max_retries, retry_delay,
                    )
                    futures[future] = step_name

                newly_ready = list(sorter.get_ready()) if sorter.is_active() else []

            if not futures:
                break   # nothing running and nothing ready — DAG complete

            # Wait for at least one step to finish before looping
            done_futures = []
            for future in list(futures.keys()):
                if future.done():
                    done_futures.append(future)

            if not done_futures:
                done_futures = [next(as_completed(futures))]

            for future in done_futures:
                step_name = futures.pop(future)
                result = future.result()
                results[step_name] = result
                if result.status != AgentStatus.SUCCESS:
                    blocked_or_failed_steps.add(step_name)
                if result.status == AgentStatus.NEEDS_REVIEW:
                    review_origins[step_name] = {step_name}
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


# ── CLI entry point ──────────────────────────────────────────────────────────
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
