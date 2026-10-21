"""task_store.py — SQLite-backed task state persistence for the BIFlow DAG runner.

Responsibility (Samar — BO1-01):
  - Record every task's state (PENDING, RUNNING, SUCCESS, FAILED, SKIPPED).
  - Allow the DAG runner to resume a partially-completed run.
  - Provide a simple read API for the Streamlit dashboard.

Table: tasks(run_id, step, status, started_at, finished_at, message, outputs_json)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

DEFAULT_DB = Path("runs/task_store.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    run_id      TEXT NOT NULL,
    step        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'PENDING',
    started_at  TEXT,
    finished_at TEXT,
    message     TEXT DEFAULT '',
    outputs_json TEXT DEFAULT '{}',
    PRIMARY KEY (run_id, step)
);
CREATE INDEX IF NOT EXISTS tasks_run ON tasks(run_id);
"""


class TaskStatus(str, Enum):
    PENDING  = "PENDING"
    RUNNING  = "RUNNING"
    SUCCESS  = "SUCCESS"
    FAILED   = "FAILED"
    SKIPPED  = "SKIPPED"


def _connect(db: Path) -> sqlite3.Connection:
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def init_run(run_id: str, steps: list[str], db: Path = DEFAULT_DB) -> None:
    """Register all steps as PENDING for a new run (idempotent)."""
    conn = _connect(db)
    try:
        conn.execute("BEGIN")
        for step in steps:
            conn.execute(
                "INSERT OR IGNORE INTO tasks(run_id, step, status) VALUES (?, ?, ?)",
                (run_id, step, TaskStatus.PENDING),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def set_running(run_id: str, step: str, db: Path = DEFAULT_DB) -> None:
    conn = _connect(db)
    try:
        conn.execute(
            "UPDATE tasks SET status=?, started_at=? WHERE run_id=? AND step=?",
            (TaskStatus.RUNNING, _now(), run_id, step),
        )
    finally:
        conn.close()


def set_done(
    run_id: str,
    step: str,
    status: TaskStatus,
    message: str = "",
    outputs: dict | None = None,
    db: Path = DEFAULT_DB,
) -> None:
    conn = _connect(db)
    try:
        conn.execute(
            "UPDATE tasks SET status=?, finished_at=?, message=?, outputs_json=? "
            "WHERE run_id=? AND step=?",
            (status, _now(), message, json.dumps(outputs or {}), run_id, step),
        )
    finally:
        conn.close()


def get_status(run_id: str, step: str, db: Path = DEFAULT_DB) -> TaskStatus | None:
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT status FROM tasks WHERE run_id=? AND step=?", (run_id, step)
        ).fetchone()
        return TaskStatus(row["status"]) if row else None
    finally:
        conn.close()


def get_run_summary(run_id: str, db: Path = DEFAULT_DB) -> list[dict]:
    """Return all task records for a run, ordered by step."""
    conn = _connect(db)
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
