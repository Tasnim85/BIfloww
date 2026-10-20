"""Put the SECOND dataset (clinics in Tunisia, fees in TND) into runs/ to show it in Streamlit.

    python -m auditor.dev.make_clinics_demo           (add --llm for an LLM-written summary)

Writes runs/clinic_001/ with the same contract files the other agents would produce, then runs
the REAL agents on it, unchanged: comparisons (BO4-12) and the auditor (SHAP + integrity).
The KPI catalog of this run lives in runs/clinic_001/static/kpi/catalog.yaml: the Olist catalog
(kpi/catalog.yaml) is not touched. Decisions go to their own journal, runs/clinics_journal.db.
Run it again at any time: it starts from scratch.
"""
import argparse
import shutil

from auditor.agent import run as run_auditor
from auditor.dev import clinics
from comparisons.checker import run as run_checker
from contracts.pipeline import RUNS_ROOT, context_for

RUN = "clinic_001"
JOURNAL = RUNS_ROOT / "clinics_journal.db"


def main(llm: bool = False) -> None:
    shutil.rmtree(RUNS_ROOT / RUN, ignore_errors=True)
    JOURNAL.unlink(missing_ok=True)
    df = clinics.visits()
    clinics.write_run(RUNS_ROOT.parent, RUN, df, own_catalog=True)      # -> runs/clinic_001/
    print(f"OK {RUN}: {len(df)} visits, 2023-10-01 -> 2024-03-20, fees in TND (no Olist name anywhere)")

    res = run_checker(context_for("comparisons", RUN, journal=JOURNAL, params={"llm": llm}))
    print(f"OK comparisons agent: {res.status.value} | {res.message}")
    res = run_auditor(context_for("auditor", RUN, journal=JOURNAL, params={"n_normal": 5}))
    print(f"OK auditor agent: {res.status.value} | {res.message}")
    print(f"OK journal -> {JOURNAL}\n"
          "Now: streamlit run auditor/ui/app.py  ->  'Résultat d'un run', pick clinic_001 in the sidebar")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--llm", action="store_true", help="summary written by the LLM (fact-checked)")
    main(ap.parse_args().llm)
