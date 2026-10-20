"""Step 1 (Tasnim): build, from the real Olist CSVs, the inputs that Ahmed's agents
will produce later. Lets comparisons/ and auditor/ be built and tested alone.

    python -m auditor.dev.make_fake_inputs                 # CSVs in data/olist/
    python -m auditor.dev.make_fake_inputs --data D:/path/to/csvs --run run_001

Writes (paths fixed by contracts/pipeline.py, existing files are replaced):
  runs/<run>/profiling/coverage_profile.json   orders per day, by status   (BO4-12)
  runs/<run>/profiling/anomaly_model.joblib    IsolationForest on payments (SHAP)
  runs/<run>/profiling/anomaly_scores.parquet  payment_id + features + score + is_anomaly
  runs/<run>/profiling/anomaly_report.json
  runs/<run>/etl/warehouse.duckdb              fact_payments, dim_customer, dim_date
  runs/<run>/etl/warehouse_manifest.json
  runs/<run>/etl/receipts.json

Every file is validated against its contract after writing.
These are STAND-INS: when Ahmed delivers the real ones, delete this script's outputs.
Nothing is written to the audit journal (fake decisions must not enter the real history).
"""
import argparse
import hashlib
from pathlib import Path

import duckdb
import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

from contracts.common import load, save
from contracts.pipeline import context_for, output_path
from contracts.quality import AnomalyReport, CoverageProfile, DayCoverage, TableCoverage
from contracts.warehouse import (TableKind, TransformationReceipt, TransformationReceipts,
                                 WarehouseManifest, WarehouseTable)

FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "customers": "olist_customers_dataset.csv",
}
FEATURES = ["payment_value", "payment_installments", "payment_sequential"]
COMPLETENESS_COLUMNS = ["order_approved_at", "order_delivered_customer_date"]
MODEL_PARAMS = {"n_estimators": 100, "contamination": 0.01, "random_state": 42}


def read_csvs(data_dir: Path) -> dict[str, pd.DataFrame]:
    missing = [f for f in FILES.values() if not (data_dir / f).exists()]
    if missing:
        raise SystemExit(f"Missing in {data_dir}: {', '.join(missing)}. "
                         f"Copy the Olist CSVs there or pass --data <folder>.")
    tables = {name: pd.read_csv(data_dir / f) for name, f in FILES.items()}
    tables["orders"]["order_purchase_timestamp"] = pd.to_datetime(
        tables["orders"]["order_purchase_timestamp"])
    return tables


# ---- 1. Coverage profile (DQ measures completeness) --------------------------------
def build_coverage(orders: pd.DataFrame) -> CoverageProfile:
    day = orders["order_purchase_timestamp"].dt.normalize()
    all_days = pd.date_range(day.min(), day.max(), freq="D")   # days without orders included
    by_day = {d: g for d, g in orders.groupby(day)}
    out = []
    for d in all_days:
        g = by_day.get(d)
        if g is None:
            out.append(DayCoverage(date=d.date().isoformat(), rows=0))
            continue
        out.append(DayCoverage(
            date=d.date().isoformat(), rows=len(g),
            by_status={str(k): int(v) for k, v in g["order_status"].value_counts().items()},
            completeness={c: round(float(g[c].notna().mean()), 4) for c in COMPLETENESS_COLUMNS}))
    return CoverageProfile(tables=[TableCoverage(
        table="orders", date_column="order_purchase_timestamp", status_column="order_status",
        first_day=out[0].date, last_day=out[-1].date, days=out)])


# ---- 2. Anomaly model on payments (what the Auditor explains with SHAP) -----------
def build_anomalies(payments: pd.DataFrame, run: str) -> AnomalyReport:
    df = payments.copy()
    df["payment_id"] = df["order_id"] + "_" + df["payment_sequential"].astype(str)
    assert df["payment_id"].is_unique, "payment_id must identify one row"

    model = IsolationForest(**MODEL_PARAMS).fit(df[FEATURES])
    scores = df[["payment_id"] + FEATURES].copy()
    scores["anomaly_score"] = -model.score_samples(df[FEATURES])   # higher = more anomalous
    scores["is_anomaly"] = model.predict(df[FEATURES]) == -1

    joblib.dump(model, output_path(run, "profiling", "model"))
    scores.to_parquet(output_path(run, "profiling", "scores"), index=False)
    return AnomalyReport(
        table="order_payments", row_key="payment_id", model="IsolationForest",
        model_version="iforest@1.0-fake", params=MODEL_PARAMS, features=FEATURES,
        n_rows=len(scores), n_anomalies=int(scores["is_anomaly"].sum()))


# ---- 3. Mini warehouse in DuckDB ------------------------------------------------------
def build_warehouse(t: dict[str, pd.DataFrame], run: str):
    orders, payments, customers = t["orders"], t["order_payments"], t["customers"]

    delivered = orders[orders["order_status"] == "delivered"]
    fact = payments.merge(
        delivered[["order_id", "customer_id", "order_purchase_timestamp", "order_status"]],
        on="order_id", how="inner")
    fact["order_purchase_date"] = fact["order_purchase_timestamp"].dt.date
    fact = fact[["order_id", "payment_sequential", "payment_type", "payment_installments",
                 "payment_value", "customer_id", "order_purchase_date", "order_status"]]

    dim_customer = customers[["customer_id", "customer_unique_id",
                              "customer_city", "customer_state"]].copy()
    dim_customer["customer_unique_id"] = dim_customer["customer_unique_id"].map(  # stand-in for PII step
        lambda v: hashlib.sha256(f"fake-salt:{v}".encode()).hexdigest()[:16])

    dates = pd.date_range(orders["order_purchase_timestamp"].min().normalize(),
                          orders["order_purchase_timestamp"].max().normalize(), freq="D")
    dim_date = pd.DataFrame({"date": dates.date, "year": dates.year, "month": dates.month,
                             "year_month": dates.strftime("%Y-%m"), "weekday": dates.day_name()})

    db_path = output_path(run, "etl", "warehouse")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    for name, frame in {"fact_payments": fact, "dim_customer": dim_customer, "dim_date": dim_date}.items():
        con.register("frame", frame)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM frame")
        con.unregister("frame")
    con.close()

    fd = pd.to_datetime(fact["order_purchase_date"])
    manifest = WarehouseManifest(tables=[
        WarehouseTable(name="fact_payments", kind=TableKind.FACT, grain="payment",
                       primary_key=["order_id", "payment_sequential"], row_count=len(fact),
                       columns=list(fact.columns), date_column="order_purchase_date",
                       date_min=fd.min().date().isoformat(), date_max=fd.max().date().isoformat()),
        WarehouseTable(name="dim_customer", kind=TableKind.DIMENSION, grain="customer",
                       primary_key=["customer_id"], row_count=len(dim_customer),
                       columns=list(dim_customer.columns)),
        WarehouseTable(name="dim_date", kind=TableKind.DIMENSION, grain="day",
                       primary_key=["date"], row_count=len(dim_date), columns=list(dim_date.columns)),
    ])
    receipts = TransformationReceipts(receipts=[TransformationReceipt(
        output_table="fact_payments", source_tables=["order_payments", "orders"],
        join_keys=["order_id"], rows_before=len(payments), rows_after=len(fact), grain="payment",
        filters=["order_status == 'delivered'"],
        column_sources={"payment_value": "order_payments.payment_value",
                        "payment_type": "order_payments.payment_type",
                        "order_purchase_date": "orders.order_purchase_timestamp",
                        "order_status": "orders.order_status"})])
    return manifest, receipts


def sanity_check(run: str) -> None:
    """Revenue figures used in the BO4-12 example must come out of this warehouse."""
    con = duckdb.connect(str(output_path(run, "etl", "warehouse")), read_only=True)
    q = ("SELECT ROUND(SUM(payment_value), 2) FROM fact_payments "
         "WHERE order_purchase_date BETWEEN ? AND ?")
    for label, a, b in [("August 2018 (full)", "2018-08-01", "2018-08-31"),
                        ("July 2018 (full)  ", "2018-07-01", "2018-07-31"),
                        ("1-23 August 2018  ", "2018-08-01", "2018-08-23"),
                        ("1-23 July 2018    ", "2018-07-01", "2018-07-23")]:
        print(f"   revenue {label}: {con.execute(q, [a, b]).fetchone()[0]:>12,.2f} BRL")
    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data/olist"))
    parser.add_argument("--run", default="run_001")
    args = parser.parse_args()

    print(f"Reading Olist CSVs from {args.data} ...")
    t = read_csvs(args.data)

    coverage = build_coverage(t["orders"])
    save(coverage, output_path(args.run, "profiling", "coverage"))
    print(f"OK coverage profile: {len(coverage.tables[0].days)} days "
          f"({coverage.tables[0].first_day} -> {coverage.tables[0].last_day})")

    anomalies = build_anomalies(t["order_payments"], args.run)
    save(anomalies, output_path(args.run, "profiling", "anomalies"))
    print(f"OK anomaly model: {anomalies.n_anomalies} anomalies out of {anomalies.n_rows} payments")

    manifest, receipts = build_warehouse(t, args.run)
    save(manifest, output_path(args.run, "etl", "manifest"))
    save(receipts, output_path(args.run, "etl", "receipts"))
    r = receipts.receipts[0]
    print(f"OK warehouse: fact_payments {r.rows_after} rows (from {r.rows_before} payments, delivered only)")
    sanity_check(args.run)

    # Every written JSON must still match its contract
    load(CoverageProfile, output_path(args.run, "profiling", "coverage"))
    load(AnomalyReport, output_path(args.run, "profiling", "anomalies"))
    load(WarehouseManifest, output_path(args.run, "etl", "manifest"))
    load(TransformationReceipts, output_path(args.run, "etl", "receipts"))

    for step in ["comparisons", "auditor"]:
        missing = [k for k, p in context_for(step, args.run).inputs.items() if not Path(p).exists()]
        print(f"{'OK' if not missing else 'MISSING'} inputs of '{step}'"
              + (f": {missing}" if missing else ": all present"))


if __name__ == "__main__":
    main()
