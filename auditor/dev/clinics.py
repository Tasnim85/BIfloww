"""A SECOND dataset, unlike Olist on purpose, to prove Tasnim's agents are dataset-agnostic.

A network of clinics in Tunisia: visits, fees in TND, a 'completed' status. It writes,
under a temporary folder, exactly the contract files the other agents would produce
(coverage profile, anomaly model + scores, warehouse, manifest, receipts, lineage,
KPI catalog, request). No Olist name appears anywhere.

Used by tests/test_generalization.py (temporary folder) and by
python -m auditor.dev.make_clinics_demo (puts it in runs/ for the Streamlit app).

Traps built in (each one is checked in test_generalization.py):
  - the coverage profile holds TWO dated tables, the wrong one first;
  - March 2024 is complete only up to the 13th (extraction lag), then volume collapses;
  - March (31 days) vs February 2024 (29 days, leap year): a length difference;
  - a new clinic in Gabes opens on 2024-03-05: a region present in one period only;
  - Sundays are naturally quiet (must not be taken for missing data).
"""
from datetime import date, timedelta
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import IsolationForest

from contracts.common import Period, save
from contracts.pipeline import output_path
from contracts.quality import AnomalyReport, CoverageProfile, DayCoverage, TableCoverage
from contracts.semantic import AnalysisRequest, Dimension, KpiCatalog, KpiDefinition
from contracts.warehouse import (LineageEdge, LineageGraph, LineageNode, NodeKind, TableKind,
                                 TransformationReceipt, TransformationReceipts, WarehouseManifest,
                                 WarehouseTable)

FEATURES = ["fee_tnd", "duration_min", "n_procedures"]
START, END = date(2023, 10, 1), date(2024, 3, 20)
LAG_FROM = date(2024, 3, 14)                 # extraction lag: incomplete from this day on
GABES_OPENS = date(2024, 3, 5)
KPI = KpiDefinition(
    name="Consultation revenue", version="1.0", description="Fees of completed visits.",
    expression="SUM(fee_tnd)", table="fact_visits", grain="visit", date_column="visit_date",
    unit="TND", filters=["visit_state = 'completed'"], population="Fees of completed visits.",
    allowed_dimensions=["region"])
CATALOG = KpiCatalog(version="1.0", kpis=[KPI], dimensions=[
    Dimension(name="region", table="dim_clinic", column="region", description="Region of the clinic.")])
CLINICS = pd.DataFrame({
    "clinic_id": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"],
    "region": ["Tunis", "Tunis", "Tunis", "Sousse", "Sousse", "Sfax", "Sfax", "Nabeul", "Gabes"],
    "city": ["Tunis", "Ariana", "Ben Arous", "Sousse", "Monastir", "Sfax", "Sfax", "Nabeul", "Gabes"],
})


def visits(seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    day = START
    while day <= END:
        base = 35 if day.weekday() == 6 else 120                  # quiet Sundays
        if day >= LAG_FROM:
            base = int(base * (0.3 if day < LAG_FROM + timedelta(days=4) else 0.1))
        n = rng.poisson(base)
        open_clinics = CLINICS["clinic_id"][: 9 if day >= GABES_OPENS else 8].to_numpy()
        for _ in range(n):
            rows.append((day, rng.choice(open_clinics)))
        day += timedelta(days=1)
    df = pd.DataFrame(rows, columns=["visit_date", "clinic_id"])
    n = len(df)
    df.insert(0, "visit_id", [f"V{i:06d}" for i in range(n)])
    df["visit_datetime"] = pd.to_datetime(df["visit_date"]) + pd.to_timedelta(rng.integers(8, 18, n), unit="h")
    df["visit_state"] = rng.choice(["completed", "cancelled", "no_show"], n, p=[0.92, 0.05, 0.03])
    df["fee_tnd"] = np.round(rng.lognormal(np.log(60), 0.35, n), 3)
    df["duration_min"] = np.clip(rng.normal(25, 8, n), 5, None).round()
    df["n_procedures"] = rng.poisson(1, n) + 1
    odd = rng.choice(n, 25, replace=False)                        # a few genuinely odd visits
    df.loc[odd[:10], "fee_tnd"] *= 12
    df.loc[odd[10:], "n_procedures"] += 9
    return df


def coverage(df: pd.DataFrame) -> CoverageProfile:
    days = pd.date_range(START, END, freq="D").date
    by_day = {d: g for d, g in df.groupby("visit_date")}
    visit_days = []
    for d in days:
        g = by_day.get(d)
        visit_days.append(DayCoverage(date=d.isoformat(), rows=0) if g is None else DayCoverage(
            date=d.isoformat(), rows=len(g),
            by_status={k: int(v) for k, v in g["visit_state"].value_counts().items()},
            completeness={"fee_tnd": 1.0}))
    decoy = TableCoverage(table="appointments", date_column="created_at", first_day=START.isoformat(),
                          last_day=END.isoformat(),
                          days=[DayCoverage(date=d.isoformat(), rows=200) for d in days])
    real = TableCoverage(table="visits", date_column="visit_datetime", status_column="visit_state",
                         first_day=START.isoformat(), last_day=END.isoformat(), days=visit_days)
    return CoverageProfile(tables=[decoy, real])                  # the wrong table FIRST


def write_run(root: Path, run_id: str, df: pd.DataFrame, model: IsolationForest | None = None,
              labels: bool = True, request: AnalysisRequest | None = None,
              own_catalog: bool = False) -> IsolationForest:
    """All contract files of one run of the clinics pipeline, under root/runs/<run_id>/.
    own_catalog=True puts the KPI catalog in runs/<run_id>/static/ (the run's own copy) instead
    of root/kpi/: used in the real repo, so the Olist catalog is never overwritten."""
    runs = root / "runs"
    if model is None:
        model = IsolationForest(n_estimators=100, contamination=0.01, random_state=0).fit(df[FEATURES])
    scores = df[["visit_id"] + FEATURES].copy()
    scores["anomaly_score"] = -model.score_samples(df[FEATURES])
    scores["is_anomaly"] = model.predict(df[FEATURES]) == -1
    out = output_path(run_id, "profiling", "scores", runs)
    out.parent.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(out, index=False)
    joblib.dump(model, output_path(run_id, "profiling", "model", runs))
    save(AnomalyReport(
        table="visits", row_key="visit_id", model="IsolationForest", model_version="iforest-clinics@1.0",
        params={"contamination": 0.01}, features=FEATURES,
        feature_labels={"fee_tnd": "Consultation fee", "n_procedures": "Number of procedures"} if labels else {},
        feature_units={"fee_tnd": "TND", "duration_min": "min"} if labels else {},
        n_rows=len(scores), n_anomalies=int(scores["is_anomaly"].sum())),
        output_path(run_id, "profiling", "anomalies", runs))
    save(coverage(df), output_path(run_id, "profiling", "coverage", runs))

    # warehouse (all states kept: the KPI filter selects 'completed')
    fact = df[["visit_id", "clinic_id", "visit_date", "visit_state"] + FEATURES]
    wh = output_path(run_id, "etl", "warehouse", runs)
    wh.parent.mkdir(parents=True, exist_ok=True)
    wh.unlink(missing_ok=True)
    with duckdb.connect(str(wh)) as con:
        for name, frame in {"fact_visits": fact, "dim_clinic": CLINICS}.items():
            con.register("frame", frame)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM frame")
            con.unregister("frame")
    save(WarehouseManifest(tables=[
        WarehouseTable(name="fact_visits", kind=TableKind.FACT, grain="visit", primary_key=["visit_id"],
                       row_count=len(fact), columns=list(fact.columns), date_column="visit_date",
                       date_min=str(fact["visit_date"].min()), date_max=str(fact["visit_date"].max())),
        WarehouseTable(name="dim_clinic", kind=TableKind.DIMENSION, grain="clinic",
                       primary_key=["clinic_id"], row_count=len(CLINICS), columns=list(CLINICS.columns))]),
        output_path(run_id, "etl", "manifest", runs))
    save(TransformationReceipts(receipts=[TransformationReceipt(
        output_table="fact_visits", source_tables=["visits"], rows_before=len(df), rows_after=len(fact),
        grain="visit", column_sources={"visit_date": "visits.visit_datetime", "fee_tnd": "visits.fee_tnd"})]),
        output_path(run_id, "etl", "receipts", runs))
    save(LineageGraph(
        nodes=[LineageNode(id="raw:visits.fee_tnd", kind=NodeKind.RAW_COLUMN, label="visits.csv / fee_tnd"),
               LineageNode(id="table:fact_visits", kind=NodeKind.TABLE, label="fact_visits"),
               LineageNode(id=f"kpi:{KPI.ref}", kind=NodeKind.KPI, label=f"{KPI.name} = {KPI.expression}")],
        edges=[LineageEdge(source="raw:visits.fee_tnd", target="table:fact_visits", relation="copied"),
               LineageEdge(source="table:fact_visits", target=f"kpi:{KPI.ref}",
                           relation="aggregated SUM(fee_tnd) of completed visits")]),
        output_path(run_id, "lineage", "graph", runs))
    save(request or AnalysisRequest(
        question="Consultation revenue by region, March vs February 2024", metric=KPI.name,
        dimensions=["region"], period=Period(start="2024-03-01", end="2024-03-31"),
        compare_to=Period(start="2024-02-01", end="2024-02-29")),
        output_path(run_id, "request", "request", runs))

    catalog = (runs / run_id / "static" if own_catalog else root) / "kpi" / "catalog.yaml"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(yaml.safe_dump(CATALOG.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return model
