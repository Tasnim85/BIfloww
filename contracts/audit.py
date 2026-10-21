"""Contract 4: the shared audit journal. Owner: Tasnim.

EVERY agent writes to it with log_event(). The Auditor reads it.
Append-only and tamper-evident:
  * SQLite triggers refuse UPDATE and DELETE through normal use;
  * each entry stores the SHA-256 hash of the previous one (a hash chain),
    so editing the file directly is detected by verify_journal().
SQLite (not a text file) because agents run IN PARALLEL: a transaction makes
"read the last hash + append" atomic, so two agents never break the chain.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from contracts.common import Contract

DEFAULT_JOURNAL = Path("runs/audit_journal.db")
GENESIS_HASH = "0" * 64


class AuditEvent(Contract):
    """One line of the journal: who did what, when, why, with which proof."""
    run_id: str
    agent: str                        # who: an AgentName value, e.g. "cleaning"
    step: str                         # what, e.g. "fill_missing", "join_multiplicity_check"
    decision: str                     # e.g. "PASSED", "FAILED", "filled 4 values with median"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    inputs: list[str] = Field(default_factory=list)    # files or tables read
    outputs: list[str] = Field(default_factory=list)   # files or tables written
    rule_version: str | None = None   # "kpi:Revenue@2.0", "playbook:olist@1.3", "model:iforest@1"
    evidence: dict = Field(default_factory=dict)       # JSON-serializable facts behind the decision


class JournalEntry(AuditEvent):
    """An AuditEvent as stored: position in the chain + hashes."""
    entry_id: int
    prev_hash: str
    entry_hash: str


class IntegrityReport(Contract):
    ok: bool
    entries_checked: int
    first_bad_entry: int | None = None
    problem: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    entry_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    agent        TEXT NOT NULL,
    step         TEXT NOT NULL,
    decision     TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    inputs       TEXT NOT NULL,
    outputs      TEXT NOT NULL,
    rule_version TEXT,
    evidence     TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_run ON journal(run_id);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
BEGIN SELECT RAISE(ABORT, 'journal is append-only: UPDATE is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
BEGIN SELECT RAISE(ABORT, 'journal is append-only: DELETE is forbidden'); END;
"""

_FIELDS = ["run_id", "agent", "step", "decision", "timestamp", "inputs",
           "outputs", "rule_version", "evidence"]


def _row_values(event: AuditEvent) -> dict:
    """The event as the exact text stored in the database (what gets hashed)."""
    return {
        "run_id": event.run_id,
        "agent": event.agent,
        "step": event.step,
        "decision": event.decision,
        "timestamp": event.timestamp.isoformat(),
        "inputs": json.dumps(event.inputs, ensure_ascii=False),
        "outputs": json.dumps(event.outputs, ensure_ascii=False),
        "rule_version": event.rule_version,
        "evidence": json.dumps(event.evidence, ensure_ascii=False, sort_keys=True, default=str),
    }


def compute_hash(prev_hash: str, values: dict) -> str:
    payload = json.dumps([prev_hash] + [values[f] for f in _FIELDS], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _connect(journal: Path) -> sqlite3.Connection:
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(journal, timeout=30, isolation_level=None)  # we manage transactions
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def log_event(event: AuditEvent, journal: Path = DEFAULT_JOURNAL) -> JournalEntry:
    """Append one event at the end of the chain. Safe with agents running in parallel."""
    values = _row_values(event)
    conn = _connect(journal)
    try:
        conn.execute("BEGIN IMMEDIATE")          # lock: nobody else appends meanwhile
        last = conn.execute("SELECT entry_hash FROM journal ORDER BY entry_id DESC LIMIT 1").fetchone()
        prev_hash = last["entry_hash"] if last else GENESIS_HASH
        entry_hash = compute_hash(prev_hash, values)
        cur = conn.execute(
            f"INSERT INTO journal ({', '.join(_FIELDS)}, prev_hash, entry_hash) "
            f"VALUES ({', '.join('?' * (len(_FIELDS) + 2))})",
            [values[f] for f in _FIELDS] + [prev_hash, entry_hash],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return JournalEntry(**event.model_dump(), entry_id=cur.lastrowid,
                        prev_hash=prev_hash, entry_hash=entry_hash)


def _to_entry(r: sqlite3.Row) -> JournalEntry:
    return JournalEntry(
        entry_id=r["entry_id"], run_id=r["run_id"], agent=r["agent"], step=r["step"],
        decision=r["decision"], timestamp=datetime.fromisoformat(r["timestamp"]),
        inputs=json.loads(r["inputs"]), outputs=json.loads(r["outputs"]),
        rule_version=r["rule_version"], evidence=json.loads(r["evidence"]),
        prev_hash=r["prev_hash"], entry_hash=r["entry_hash"],
    )


def read_events(journal: Path = DEFAULT_JOURNAL, run_id: str | None = None,
                agent: str | None = None) -> list[JournalEntry]:
    """Read the journal (optionally one run and/or one agent), oldest first."""
    if not Path(journal).exists():
        return []
    conn = _connect(journal)
    try:
        sql, args = "SELECT * FROM journal WHERE 1=1", []
        if run_id:
            sql, args = sql + " AND run_id = ?", args + [run_id]
        if agent:
            sql, args = sql + " AND agent = ?", args + [agent]
        return [_to_entry(r) for r in conn.execute(sql + " ORDER BY entry_id", args)]
    finally:
        conn.close()


def last_hash(journal: Path = DEFAULT_JOURNAL) -> str:
    """The 'anchor': store it elsewhere to detect even a fully recomputed chain."""
    entries = read_events(journal)
    return entries[-1].entry_hash if entries else GENESIS_HASH


def verify_journal(journal: Path = DEFAULT_JOURNAL) -> IntegrityReport:
    """Recompute every hash. Detects any entry edited, removed or inserted."""
    if not Path(journal).exists():
        return IntegrityReport(ok=True, entries_checked=0, problem="Journal is empty.")
    conn = _connect(journal)
    try:
        rows = conn.execute("SELECT * FROM journal ORDER BY entry_id").fetchall()
    finally:
        conn.close()
    expected_prev = GENESIS_HASH
    for r in rows:
        if r["prev_hash"] != expected_prev:
            return IntegrityReport(ok=False, entries_checked=len(rows), first_bad_entry=r["entry_id"],
                                   problem=f"Entry {r['entry_id']}: broken link. An earlier entry "
                                           f"was altered, removed or inserted.")
        if compute_hash(r["prev_hash"], {f: r[f] for f in _FIELDS}) != r["entry_hash"]:
            return IntegrityReport(ok=False, entries_checked=len(rows), first_bad_entry=r["entry_id"],
                                   problem=f"Entry {r['entry_id']}: content does not match its hash. "
                                           f"It was modified after being written.")
        expected_prev = r["entry_hash"]
    return IntegrityReport(ok=True, entries_checked=len(rows),
                           problem="All entries verified: the chain is intact.")
