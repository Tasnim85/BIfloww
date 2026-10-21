"""Profiling and keys work on a dataset that is not Olist: French column names, no 'orders' table."""
import json

import duckdb
import pandas as pd

from contracts import AgentStatus, RunContext, read_events
from contracts.registry import read_output
from etl.generic import is_key_name, key_columns, relationships, inventory, digest
from etl.dimensional_design import profile, Plan, Role, validate
import etl.build
import profiling.profiler
from profiling.autodetect import coverage_settings

# A small clinic: patients, appointments (rendez-vous), invoices (factures) in 2 parts.
PATIENTS = pd.DataFrame({"id_patient": [1, 2, 3, 4], "ville": ["Tunis", "Sfax", "Tunis", "Sousse"],
                         "date_naissance": ["1980-01-02", "1975-05-06", "1990-03-04", "2000-07-08"]})
RDV = pd.DataFrame({"num_rdv": [f"R{i}" for i in range(12)], "id_patient": [1 + i % 4 for i in range(12)],
                    "specialite": ["dentaire", "pediatrie", "cardiologie"] * 4,
                    "statut": ["honore" if i % 5 else "annule" for i in range(12)],
                    "date_rdv": [f"2026-0{8 + i % 2}-{1 + i:02d} 09:30" for i in range(12)],
                    "date_rappel": [f"2026-0{8 + i % 2}-{2 + i:02d} 08:00" for i in range(12)]})
FACTURES = pd.DataFrame({"num_rdv": [f"R{i}" for i in range(12) for _ in (0, 1)],
                         "ligne": [k + 1 for i in range(12) for k in (0, 1)],
                         "montant": [40.0 + i * 5 + k for i in range(12) for k in (0, 1)],
                         "remise": [float(i % 3) for i in range(12) for _ in (0, 1)]})


def test_key_names_in_any_language():
    for column in ["order_id", "id_client", "num_commande", "CustomerID", "code_postal", "Nº_facture"]:
        assert is_key_name(column), column
    for column in ["order_status", "ville", "montant", "video", "idade"]:
        assert not is_key_name(column), column


def test_keys_and_links_of_a_french_dataset():
    frames = {"patients": PATIENTS, "rdv": RDV, "factures": FACTURES}
    shared = lambda t: {c for c in frames[t] for o in frames if o != t and c in frames[o]}
    assert key_columns(PATIENTS, shared("patients")) == ["id_patient"]
    assert key_columns(RDV, shared("rdv")) == ["num_rdv"]
    assert key_columns(FACTURES, shared("factures")) == ["num_rdv", "ligne"]   # line number = 2nd part of the key
    metadata = {t: {"primary_key": key_columns(f, shared(t))} for t, f in frames.items()}
    links = {(l["child"], l["parent"]) for l in relationships(frames, metadata)}
    assert links == {("rdv", "patients"), ("factures", "rdv")}


def test_profiling_chooses_its_settings_when_nobody_gives_them(tmp_path):
    tables = tmp_path / "pii" / "tables"; tables.mkdir(parents=True)
    for name, frame in {"patients": PATIENTS, "rdv": RDV, "factures": FACTURES}.items():
        frame.to_parquet(tables / f"{name}.parquet", index=False)
    journal = tmp_path / "journal.db"
    result = profiling.profiler.run(RunContext(run_id="t1", agent="profiling", inputs={"tables": tables},
                                               output_dir=tmp_path / "profiling", params={}, journal=journal))
    assert result.status == AgentStatus.SUCCESS, result.message

    cov = read_output(result.outputs["coverage"], "profiling.coverage")      # valid against contracts v1.1
    table = cov.tables[0]
    assert (table.table, table.date_column, table.status_column) == ("rdv", "date_rdv", "statut")
    assert (table.first_day, table.last_day) == ("2026-08-01", "2026-09-12")
    assert sum(d.by_status.get("annule", 0) for d in table.days) == 3

    anomalies = read_output(result.outputs["anomalies"], "profiling.anomalies")
    assert anomalies.table == "factures" and anomalies.features == ["montant", "remise"]

    settings = {e.step: e.evidence for e in read_events(journal) if e.step.endswith("_settings")}
    assert settings["coverage_settings"]["reason"].startswith("auto:")   # the choice is explained in the journal


def test_olist_keeps_the_settings_of_the_contract_examples():
    orders = pd.DataFrame({"order_id": ["o1"], "customer_id": ["c1"], "order_status": ["delivered"],
                           "order_purchase_timestamp": ["2018-08-01 10:00"], "order_approved_at": ["2018-07-01 10:00"]})
    table, date, status, identifier, reason = coverage_settings({"orders": orders}, {})
    assert (table, date, status, identifier) == ("orders", "order_purchase_timestamp", "order_status", "order_id")


def test_warehouse_of_a_french_dataset_can_be_joined(tmp_path):
    tables = tmp_path / "cleaning" / "tables"; tables.mkdir(parents=True)
    for name, frame in {"patients": PATIENTS, "rdv": RDV, "factures": FACTURES}.items():
        frame.to_parquet(tables / f"{name}.parquet", index=False)
    (tmp_path / "cleaning" / "cleaning_report.json").write_text(json.dumps({"needs_review": []}))
    out = tmp_path / "etl"; out.mkdir()
    ctx = RunContext(run_id="t1", agent="etl", inputs={"tables": tables, "cleaning_report": tmp_path / "cleaning/cleaning_report.json"},
                     output_dir=out, params={}, journal=tmp_path / "journal.db")
    frames, metadata, hashes = inventory(ctx); profiles = profile(frames, metadata); candidates = relationships(frames, metadata)
    by_source = {m["source"]: t for t, m in metadata.items()}
    roles = [Role(table=by_source["patients"], role="dimension", grain="patient", reason="test"),
             Role(table=by_source["rdv"], role="fact", grain="rendez-vous", dates=["date_rdv"], reason="test"),
             Role(table=by_source["factures"], role="fact", grain="ligne", measures=["montant", "remise"], reason="test")]
    plan = Plan(schema_type="constellation", rationale="test", tables=roles, relationships=[c["id"] for c in candidates])
    validate(plan, profiles, candidates)
    proposal = out / "warehouse_proposal.json"
    proposal.write_text(json.dumps({"version": 2, "cleaning_source": str(tables.parent.resolve()), "source_fingerprints": hashes,
        "tables": metadata, "profiles": profiles, "candidates": candidates, "design": plan.model_dump()}, ensure_ascii=False))
    result = etl.build.run(ctx.model_copy(update={"params": {"etl_approval": digest(proposal)}}))
    assert result.status == AgentStatus.SUCCESS, result.message

    manifest = read_output(out / "warehouse_manifest.json", "etl.manifest")
    t = {x.name: x for x in manifest.tables}
    assert t["fact_factures"].primary_key == ["num_rdv", "ligne"] and t["fact_factures"].date_column == "date_rdv_date"
    assert t["fact_rdv"].date_column == "date_rdv_date"   # not the birth date of the patient
    assert "id_patient" in t["fact_factures"].columns and t["dim_patients"].primary_key == ["id_patient"]
    con = duckdb.connect(str(out / "warehouse.duckdb"), read_only=True)
    try:
        by_city = dict(con.execute("SELECT p.ville, SUM(f.montant) FROM fact_factures f JOIN dim_patients p "
                                   "ON f.id_patient = p.id_patient JOIN dim_date d ON f.date_rdv_date = d.date "
                                   "WHERE d.year_month = '2026-08' GROUP BY 1").fetchall())
    finally:
        con.close()
    assert sum(by_city.values()) == sum(FACTURES.montant[FACTURES.num_rdv.isin([f"R{i}" for i in range(0, 12, 2)])])
