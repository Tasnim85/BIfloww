"""Build a DEMO journal for run_001, so the "why?" agent has a whole run to talk about.

    python -m auditor.dev.seed_demo_journal            # template summary (saves LLM quota)
    python -m auditor.dev.seed_demo_journal --llm

Writes runs/demo_journal.db (NOT the real runs/audit_journal.db: illustrative events
must never enter the real history). It contains:
  - the example decisions of the other agents (contracts/examples/audit_events.json):
    PII masking, cleaning rule, ETL join check, KPI validation;
  - a REAL run of the comparisons agent (BO4-12) and Sarra accepting the fix;
  - a REAL run of the Auditor agent (SHAP explanations + integrity check).
Re-running it starts from an empty demo journal.
"""
import argparse
import json
from pathlib import Path

from auditor.agent import run as run_auditor
from comparisons.checker import record_decision, run as run_comparisons
from contracts.audit import AuditEvent, log_event, verify_journal
from contracts.pipeline import context_for

DEMO_JOURNAL = Path("runs/demo_journal.db")
EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "audit_events.json"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--llm", action="store_true", help="let the LLM write the comparison summary")
    args = p.parse_args()

    DEMO_JOURNAL.unlink(missing_ok=True)
    events = [AuditEvent.model_validate(e) for e in json.loads(EXAMPLES.read_text(encoding="utf-8"))
              if e["agent"] != "comparisons"]          # the real comparisons agent runs below
    for e in events:
        log_event(e, DEMO_JOURNAL)
    print(f"OK {len(events)} example decisions of the other agents (pii, cleaning, etl, analysis)")

    res = run_comparisons(context_for("comparisons", "run_001", journal=DEMO_JOURNAL,
                                      params={"llm": args.llm}))
    print(f"OK comparisons agent: {res.status.value} | {res.message}")
    record_decision("run_001", "accepted", "same_days", journal=DEMO_JOURNAL)
    print("OK Sarra accepted the recommended fix (same_days)")

    res = run_auditor(context_for("auditor", "run_001", journal=DEMO_JOURNAL))
    print(f"OK auditor agent: {res.status.value} | {res.message}")
    print(f"OK demo journal: {verify_journal(DEMO_JOURNAL).entries_checked} entries -> {DEMO_JOURNAL}")


if __name__ == "__main__":
    main()
