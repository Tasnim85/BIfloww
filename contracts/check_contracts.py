"""Run before every pull request that touches contracts/:

    python -m contracts.check_contracts

Checks that: the DAG has no cycle, every input points to a real output, every
example file is valid, and the journal detects tampering and survives parallel writers.
"""
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from contracts.audit import AuditEvent, log_event, read_events, verify_journal
from contracts.common import load
from contracts.pipeline import STEPS, context_for, execution_order
from contracts.quality import Playbook
from contracts.registry import CONTRACT_OF
from contracts.semantic import Glossary, KpiCatalog, load_yaml

EXAMPLES = Path(__file__).parent / "examples"


def check_dag() -> None:
    order = execution_order()
    for name, step in STEPS.items():
        for key, ref in step.inputs.items():
            if ref.startswith("static:"):
                continue
            src, out_key = ref.split(".", 1)
            assert src in STEPS, f"{name}.{key}: unknown step '{src}'"
            assert out_key in STEPS[src].outputs, f"{name}.{key}: '{src}' has no output '{out_key}'"
            assert order.index(src) < order.index(name), f"{src} must run before {name}"
    print("OK  DAG:", " -> ".join(order))


def check_examples() -> None:
    n = 0
    for ref, cls in CONTRACT_OF.items():
        step, key = ref.split(".")
        path = EXAMPLES / "run_001" / step / STEPS[step].outputs[key]
        if path.exists():
            load(cls, path)
            n += 1
    load_yaml(KpiCatalog, EXAMPLES / "static/kpi/catalog.yaml")
    load_yaml(Glossary, EXAMPLES / "static/semantic/glossary.yaml")
    load_yaml(Playbook, EXAMPLES / "static/cleaning/playbooks/olist@1.3.yaml")
    print(f"OK  {n} example JSON files + 3 YAML files are valid")


def check_journal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        journal = Path(tmp) / "journal.db"

        # 1. 40 events written by 8 agents at the same time
        def write(i: int) -> None:
            log_event(AuditEvent(run_id="run_test", agent=f"agent_{i % 8}", step="test",
                                 decision="PASSED", evidence={"i": i}), journal)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(40)))
        report = verify_journal(journal)
        assert report.ok and report.entries_checked == 40, report
        print("OK  journal: 40 parallel writes, chain intact")

        # 2. the RunContext shortcut
        ctx = context_for("comparisons", "run_test", runs_root=Path(tmp), journal=journal)
        ctx.log("coverage_check", "BLOCKING", evidence={"current_days": 29})
        assert read_events(journal, agent="comparisons")[0].evidence == {"current_days": 29}

        # 3. normal UPDATE is refused
        conn = sqlite3.connect(journal)
        try:
            conn.execute("UPDATE journal SET decision = 'HACKED' WHERE entry_id = 5")
            raise AssertionError("UPDATE was not blocked")
        except sqlite3.DatabaseError:
            pass

        # 4. an attacker drops the trigger and edits entry 5: detected
        conn.execute("DROP TRIGGER journal_no_update")
        conn.execute("UPDATE journal SET decision = 'HACKED' WHERE entry_id = 5")
        conn.commit()
        conn.close()
        report = verify_journal(journal)
        assert not report.ok and report.first_bad_entry == 5, report
        print("OK  journal: tampering with entry 5 detected ->", report.problem)


if __name__ == "__main__":
    check_dag()
    check_examples()
    check_journal()
    print("All contract checks passed.")
