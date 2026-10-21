"""Continue an integration run from one step, e.g. after approving the ETL proposal:

    python -m tools.integration.run_from integ_001 etl etl_approval=<sha256 of runs/integ_001/etl/warehouse_proposal.json> backend=json
"""
import importlib, json, sys, shutil
from pathlib import Path
R = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(R))
from contracts.pipeline import STEPS, context_for, execution_order
RUN, START = sys.argv[1], sys.argv[2]
def value(text):                                   # key=value; a JSON object or list becomes a dict / list
    return json.loads(text) if text[:1] in "{[" else text
extra = {k: value(v) for k, v in (a.split("=", 1) for a in sys.argv[3:])}
params = {"source_dir": str(R / "data/olist"), "question": "Revenue by customer state, August 2018 vs July 2018",
          "uploaded_by": "integration", "playbook": str(R / "cleaning/playbooks/playbook_v2.0.json"), **extra}
order = execution_order(); todo = order[order.index(START):]
for step in todo:
    if step == "request" and START != "request": continue      # independent of the data steps, already done
    out = R / "runs" / RUN / step
    if out.exists() and not (step == "etl" and START == "etl"): shutil.rmtree(out)   # keep the proposal to approve
    mod, fn = STEPS[step].entrypoint.split(":")
    ctx = context_for(step, RUN, runs_root=R / "runs", journal=R / f"runs/{RUN}_journal.db", params=params)
    try:
        r = getattr(importlib.import_module(mod), fn)(ctx)
        print(f"{step:13} {r.status.value:13} {r.message[:170]}")
    except Exception as e:
        print(f"{step:13} {'EXCEPTION':13} {type(e).__name__}: {str(e)[:170]}")
