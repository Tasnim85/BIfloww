"""Integration run: every real agent on the full Olist CSVs, one question with a comparison.

    set BO2_PII_SECRET=<32+ characters>          (cmd)   Ollama + llama3 running locally
    python -m tools.integration.run_all integ_001
    -> stops at the ETL review (needs_review): approve with run_from.py (see INTEGRATION.md)
"""
import json, logging, shutil, sys, time
from pathlib import Path
R = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(R))
from contracts.pipeline import STEPS
from orchestrator.dag_runner import run_pipeline
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
RUN = sys.argv[1] if len(sys.argv) > 1 else "integ_001"
SRC = sys.argv[2] if len(sys.argv) > 2 else "data/olist"
Q = sys.argv[3] if len(sys.argv) > 3 else "Revenue by customer state, August 2018 vs July 2018"
for p in [R / "runs" / RUN, R / f"runs/{RUN}_tasks.db", R / f"runs/{RUN}_journal.db"]:
    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
(R / "runs").mkdir(exist_ok=True)
t0 = time.time()
res = run_pipeline(run_id=RUN, runs_root=R / "runs", journal=R / f"runs/{RUN}_journal.db", db=R / f"runs/{RUN}_tasks.db",
                   params={"source_dir": str(R / SRC), "question": Q, "uploaded_by": "integration",  "playbook": str(R / "cleaning/playbooks/playbook_v2.0.json")}, stop_on_failure=False)
print(f"\n=== {RUN} in {time.time()-t0:.0f}s ===")
for name in STEPS:
    r = res.get(name)
    print(f"{name:13} {(r.status.value if r else 'NOT RUN'):13} {(r.message if r else '')[:150]}")
