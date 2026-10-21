"""The orchestration loop with its human reviews, end to end (an example for the orchestrator / the app).

    set BO2_PII_SECRET=<32+ characters>       Ollama + llama3 running (or tools/integration/fake_ollama.py for tests)
    python -m tools.integration.run_with_reviews integ_010

Each round runs the DAG on the SAME run_id (finished steps are reused). When a step stops for a human
(needs_review), this script answers like a reviewer who agrees with the proposal, then resumes:
  pii          -> pii_overrides: confirms the type the model proposed for each uncertain column
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
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R))

from comparisons.checker import record_decision          # noqa: E402
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
          "uploaded_by": "integration", "playbook": str(R / "cleaning/playbooks/playbook_v2.0.json"), "backend": "json"}

for p in (ROOT / RUN, DB):
    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
ROOT.mkdir(exist_ok=True)
print(f"journal: {JOURNAL.name}" + ("   (TEST DOUBLE: fake_ollama, not llama3)" if JOURNAL.name.startswith("integration") else ""))

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
            print(f"  reviewer confirms {len(params['pii_overrides'])} PII column(s)")
        elif step == "etl":
            proposal = ROOT / RUN / "etl" / "warehouse_proposal.json"
            params["etl_approval"] = hashlib.sha256(proposal.read_bytes()).hexdigest()
            print("  reviewer approves the ETL plan")
        elif step == "comparisons":
            record_decision(RUN, "accepted", runs_root=ROOT, journal=JOURNAL)
            print("  Sarra accepts the recommended fix")
