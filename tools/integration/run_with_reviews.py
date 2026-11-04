"""The orchestration loop with its human reviews, end to end (an example for the orchestrator / the app).

    set BO2_PII_SECRET=<32+ characters>       Ollama + llama3 running (or tools/integration/fake_ollama.py for tests)
    python -m tools.integration.run_with_reviews integ_010

Each round runs the DAG on the SAME run_id (finished steps are reused). When a step stops for a human
(needs_review), this script answers like a reviewer who agrees with the proposal, then resumes:
  pii          -> pii_overrides: confirms the type the model proposed for each uncertain column
  cleaning     -> cleaning_approval: approves the rules the LLM proposed when no playbook fits
  etl          -> etl_approval:  sha256 of runs/<run>/etl/warehouse_proposal.json (after check_warehouse)
  comparisons  -> record_decision(accepted): Sarra takes the recommended fix
In the real app these answers come from the screens; everything else stays the same.

Which journal: with the real llama3, the real one (runs/audit_journal.db, never deleted). With the
TEST DOUBLE (tools/integration/fake_ollama.py), runs/integration_journal.db: decisions made by a
fake model must never be mixed with real decisions. The app shows that journal with its label.
"""
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R))

from comparisons.checker import record_decision          # noqa: E402
from contracts.audit import AuditEvent, log_event        # noqa: E402
from contracts.agent import AgentStatus                  # noqa: E402
from contracts.pipeline import STEPS                     # noqa: E402
from orchestrator.dag_runner import run_pipeline         # noqa: E402

RUN = sys.argv[1] if len(sys.argv) > 1 else "integ_010"
ROOT = R / "runs"


def uses_test_double() -> bool:
    """fake_ollama answers GET /api/version with 'fake-test-double'; a real Ollama with its version."""
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        with build_opener(ProxyHandler({})).open(f"{base}/api/version", timeout=5) as r:
            return "fake" in json.loads(r.read()).get("version", "")
    except (OSError, ValueError):
        return False


JOURNAL = ROOT / ("integration_journal.db" if uses_test_double() else "audit_journal.db")   # never deleted
DB = ROOT / f"{RUN}_tasks.db"
params = {"source_dir": str(R / "data/olist"), "question": "Revenue by customer state, August 2018 vs July 2018",
          "uploaded_by": "integration", "playbook": str(R / "cleaning/playbooks/playbook_v2.0.json"), "backend": "json",
          "playbook_dir": str(ROOT / RUN / "cleaning_playbooks")}   # never write into the repo's playbooks

for p in (ROOT / RUN, DB):
    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
ROOT.mkdir(exist_ok=True)
print(f"journal: {JOURNAL.name}" + ("   (TEST DOUBLE: fake_ollama, not llama3)" if JOURNAL.name.startswith("integration") else ""))

# This script answers the reviews itself: it says so, by name, in the journal (never a person's name)
REVIEWER = "run_with_reviews (integration script)"


def journal_review(step: str, evidence: dict) -> None:
    approved_at = datetime.now(timezone.utc).isoformat()
    folder = ROOT / RUN / step
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "approval.json").write_text(json.dumps({**evidence, "reviewer": REVIEWER, "approved_at": approved_at}, indent=2),
                                          encoding="utf-8")
    log_event(AuditEvent(run_id=RUN, agent=step, step="human_review", decision=f"APPROVED by {REVIEWER}",
                         rule_version="app-review@1.0", evidence={**evidence, "reviewer": REVIEWER, "approved_at": approved_at}),
              JOURNAL)


for round_no in range(1, 6):
    res = run_pipeline(run_id=RUN, runs_root=ROOT, journal=JOURNAL, db=DB, params=params)
    print(f"\n--- round {round_no}")
    for name in STEPS:
        r = res.get(name)
        print(f"  {name:13} {(r.status.value if r else '-'):13} {(r.message if r else '')[:110]}")
    waiting = [n for n, r in res.items() if r.status == AgentStatus.NEEDS_REVIEW]
    if not waiting:
        failed = [n for n, r in res.items() if r.status == AgentStatus.FAILED]
        print("\nDONE" if not failed else f"\nFAILED steps: {failed}")
        break
    for step in waiting:
        if step == "pii":
            report = json.loads((ROOT / RUN / "pii" / "pii_report.bo2.json").read_text(encoding="utf-8"))
            kinds = {f'{c["table"]}.{c["column"]}': c["semantic_type"] for c in report["classification"]}
            params["pii_overrides"] = {k: kinds[f'{i["table"]}.{i["column"]}'] for i in report["needs_review"]
                                       for k in [f'{i["table"]}.{i["column"]}']}
            journal_review("pii", {"pii_overrides": params["pii_overrides"]})
            print(f"  reviewer confirms {len(params['pii_overrides'])} PII column(s)")
        elif step == "cleaning" and (ROOT / RUN / "cleaning" / "proposed_rules.json").exists():
            from cleaning.llm_rules import approve      # Ikbel's approval file: sha256 + reviewer + approved_at
            proposal = ROOT / RUN / "cleaning" / "proposed_rules.json"
            approval = approve(proposal, REVIEWER, ROOT / RUN / "cleaning" / "approval.json")
            params["cleaning_proposal"], params["cleaning_approval"] = str(proposal), str(approval)
            log_event(AuditEvent(run_id=RUN, agent="cleaning", step="human_review", decision=f"APPROVED by {REVIEWER}",
                                 rule_version="app-review@1.0", evidence=json.loads(approval.read_text(encoding="utf-8"))), JOURNAL)
            print("  reviewer approves the cleaning rules proposed by the LLM")
        elif step == "etl":
            proposal = ROOT / RUN / "etl" / "warehouse_proposal.json"
            params["etl_approval"] = hashlib.sha256(proposal.read_bytes()).hexdigest()
            journal_review("etl", {"proposal_sha256": params["etl_approval"]})
            print("  reviewer approves the ETL plan")
        elif step == "comparisons":
            record_decision(RUN, "accepted", reviewer=REVIEWER, runs_root=ROOT, journal=JOURNAL)
            print("  Sarra accepts the recommended fix")
