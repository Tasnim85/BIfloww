"""Builds one pipeline run per month of real Olist data, with three PLANTED events,
so the drift monitor can be tested before the real pipeline runs every month.

    python -m auditor.dev.simulate_runs        # then: python -m auditor.drift.monitor

Writes runs/run_2017_10 ... runs/run_2018_08 (profiling + etl outputs, same contracts
as the real agents) and runs/drift_truth.json (what was planted: read only by the
evaluation printout, NEVER by the monitor).

How the months are built:
  - the anomaly model is trained ONCE on the 6 reference months, then frozen
    (as in production: a model is not retrained every month);
  - each month: the month's payments are scored, flagged with the threshold that
    gives `contamination` on the training data, and an ETL receipt is written.
Planted events (the rest of the months are untouched real data):
  2018-05  agent_changed:profiling  contamination raised 0.01 -> 0.03 (a setting)
  2018-06  agent_changed:etl        the ETL silently loses 8% of the rows
  2018-07  data_drift               every payment value x1.5 (e.g. a price change)
"""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from contracts.common import save
from contracts.pipeline import RUNS_ROOT, output_path
from contracts.quality import AnomalyReport
from contracts.warehouse import TransformationReceipt, TransformationReceipts

REFERENCE_MONTHS = ["2017-10", "2017-11", "2017-12", "2018-01", "2018-02", "2018-03"]
MONITORED_MONTHS = ["2018-04", "2018-05", "2018-06", "2018-07", "2018-08"]
REFERENCE = [f"run_{m.replace('-', '_')}" for m in REFERENCE_MONTHS]
MONITORED = [f"run_{m.replace('-', '_')}" for m in MONITORED_MONTHS]
TRUTH_FILE = RUNS_ROOT / "drift_truth.json"
DRIFT_JOURNAL = RUNS_ROOT / "drift_journal.db"

FEATURES = ["payment_value", "payment_installments", "payment_sequential"]
BASE_CONTAMINATION = 0.01
PLANTED = {
    "2018-05": {"label": "agent_changed:profiling", "what": "contamination 0.01 -> 0.03",
                "contamination": 0.03},
    "2018-06": {"label": "agent_changed:etl", "what": "ETL loses 8% of rows", "etl_loss": 0.08},
    "2018-07": {"label": "data_drift", "what": "payment values x1.5", "value_factor": 1.5},
}


def load_payments(data_dir: Path) -> pd.DataFrame:
    orders = pd.read_csv(data_dir / "olist_orders_dataset.csv",
                         parse_dates=["order_purchase_timestamp"])
    pay = pd.read_csv(data_dir / "olist_order_payments_dataset.csv")
    df = pay.merge(orders[["order_id", "order_purchase_timestamp", "order_status"]], on="order_id")
    df["month"] = df["order_purchase_timestamp"].dt.strftime("%Y-%m")
    df["payment_id"] = df["order_id"] + "_" + df["payment_sequential"].astype(str)
    return df


def simulate(data_dir: Path = Path("data/olist"), runs_root: Path = RUNS_ROOT) -> dict:
    df = load_payments(data_dir)
    train = df[df["month"].isin(REFERENCE_MONTHS)][FEATURES]
    params = {"n_estimators": 100, "contamination": BASE_CONTAMINATION, "random_state": 42}
    model = IsolationForest(**params).fit(train)
    train_scores = -model.score_samples(train)
    rng = np.random.default_rng(7)
    truth = {}

    for month in REFERENCE_MONTHS + MONITORED_MONTHS:
        run = f"run_{month.replace('-', '_')}"
        plant = PLANTED.get(month, {})
        m = df[df["month"] == month].copy()
        if "value_factor" in plant:
            m["payment_value"] = (m["payment_value"] * plant["value_factor"]).round(2)

        # ---- profiling outputs (frozen model, threshold from the training data) ------
        contamination = plant.get("contamination", BASE_CONTAMINATION)
        threshold = np.quantile(train_scores, 1 - contamination)
        scores = m[["payment_id"] + FEATURES].copy()
        scores["anomaly_score"] = -model.score_samples(m[FEATURES])
        scores["is_anomaly"] = scores["anomaly_score"] > threshold
        out = output_path(run, "profiling", "scores", runs_root)
        out.parent.mkdir(parents=True, exist_ok=True)
        scores.to_parquet(out, index=False)
        joblib.dump(model, output_path(run, "profiling", "model", runs_root))
        save(AnomalyReport(table="order_payments", row_key="payment_id", model="IsolationForest",
                           model_version="iforest@1.0-monthly",
                           params=params | {"contamination": contamination}, features=FEATURES,
                           n_rows=len(scores), n_anomalies=int(scores["is_anomaly"].sum())),
             output_path(run, "profiling", "anomalies", runs_root))

        # ---- ETL receipt (delivered payments; optionally a silent loss) ---------------
        kept = int((m["order_status"] == "delivered").sum())
        if "etl_loss" in plant:
            kept = int(rng.binomial(kept, 1 - plant["etl_loss"]))
        save(TransformationReceipts(receipts=[TransformationReceipt(
            output_table="fact_payments", source_tables=["order_payments", "orders"],
            join_keys=["order_id"], rows_before=len(m), rows_after=kept, grain="payment",
            filters=["order_status == 'delivered'"])]),
            output_path(run, "etl", "receipts", runs_root))

        truth[run] = {"label": plant.get("label", "stable"), "what": plant.get("what", "nothing (real data)")}
        print(f"  {run}: {len(m):>5} payments, {int(scores['is_anomaly'].sum()):>3} flagged, "
              f"ETL kept {kept}  | planted: {truth[run]['what']}")

    path = Path(runs_root) / TRUTH_FILE.name
    path.write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return truth


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=Path("data/olist"))
    args = p.parse_args()
    print("Building one run per month (frozen model trained on the 6 reference months):")
    simulate(args.data)
    print(f"\nOK reference: {', '.join(REFERENCE)}")
    print(f"OK monitored: {', '.join(MONITORED)}")
    print(f"OK planted truth (hidden from the monitor): {TRUTH_FILE}")


if __name__ == "__main__":
    main()
