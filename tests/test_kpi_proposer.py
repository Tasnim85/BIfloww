"""The KPI proposer on a dataset that is NOT Olist: clinics in Tunisia, fees in TND.
Nothing in the code knows this dataset: the catalog comes from the manifest + warehouse."""
import json

import duckdb
import pytest

import contracts.llm as llm
from analysis.kpi_proposer import propose
from analysis.sql_compiler import compile_query
from contracts.common import Period
from contracts.semantic import AnalysisRequest
from contracts.warehouse import TableKind, WarehouseManifest, WarehouseTable


@pytest.fixture
def clinics(tmp_path):
    db = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE dim_clinic (clinic_id VARCHAR, city VARCHAR, specialty VARCHAR)")
    con.executemany("INSERT INTO dim_clinic VALUES (?, ?, ?)",
                    [("K1", "Tunis", "dental"), ("K2", "Sfax", "pediatrics"), ("K3", "Tunis", "pediatrics")])
    con.execute("CREATE TABLE fact_visits (visit_id VARCHAR, patient_id VARCHAR, clinic_id VARCHAR, "
                "visit_date DATE, fee DOUBLE)")
    con.executemany("INSERT INTO fact_visits VALUES (?, ?, ?, ?, ?)", [
        ("V1", "P1", "K1", "2024-03-02", 60.0), ("V2", "P2", "K2", "2024-03-05", 45.0),
        ("V3", "P1", "K3", "2024-03-20", 50.0), ("V4", "P3", "K1", "2024-04-01", 80.0)])
    con.close()
    manifest = WarehouseManifest(tables=[
        WarehouseTable(name="fact_visits", kind=TableKind.FACT, grain="visit", primary_key=["visit_id"],
                       row_count=4, columns=["visit_id", "patient_id", "clinic_id", "visit_date", "fee"],
                       date_column="visit_date", date_min="2024-03-02", date_max="2024-04-01"),
        WarehouseTable(name="dim_clinic", kind=TableKind.DIMENSION, grain="clinic", primary_key=["clinic_id"],
                       row_count=3, columns=["clinic_id", "city", "specialty"])])
    return manifest, db


def test_without_llm_every_candidate_is_kept_and_runs(clinics):
    manifest, db = clinics
    catalog, glossary, source = propose(manifest, db, use_llm=False)
    assert source == "mechanical"
    formulas = {k.expression for k in catalog.kpis}
    assert {"COUNT(*)", "COUNT(DISTINCT patient_id)", "SUM(fee)", "AVG(fee)"} <= formulas
    assert "COUNT(DISTINCT visit_id)" not in formulas          # the key itself: same as COUNT(*)
    assert {d.name for d in catalog.dimensions} == {"city", "specialty"}   # ids are not dimensions
    # the Analyst's compiler accepts the proposal: Revenue by city for March 2024
    kpi = next(k for k in catalog.kpis if k.expression == "SUM(fee)")
    q = compile_query(AnalysisRequest(question="t", metric=kpi.name, dimensions=["city"],
                                      period=Period(start="2024-03-01", end="2024-03-31")), catalog, manifest)
    rows = dict((r[0], r[2]) for r in duckdb.connect(str(db), read_only=True).execute(q.sql).fetchall())
    assert rows == {"Sfax": 45.0, "Tunis": 110.0}


def test_llm_names_the_candidates_but_cannot_invent(clinics, monkeypatch):
    manifest, db = clinics
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    answer = {"kpis": [
        {"candidate": "M4", "name": "Revenue", "description": "Fees paid by patients.", "unit": "TND",
         "synonyms": ["sales", "chiffre d'affaires"]},
        {"candidate": "M2", "name": "Patients", "description": "Distinct patients.", "unit": "count"},
        {"candidate": "M99", "name": "Profit", "description": "Invented.", "unit": "TND"},       # no such candidate
        {"candidate": "M5", "name": "bad name!", "description": "Bad name.", "unit": "TND"}],     # refused name
        "dimensions": [{"candidate": "D1", "name": "clinic_city", "description": "City of the clinic.",
                        "synonyms": ["city", "ville"]}]}
    sent = []

    def fake_post(url, payload, timeout, headers=None):
        sent.append(payload)
        return {"choices": [{"message": {"content": json.dumps(answer)}}]}
    monkeypatch.setattr(llm, "_post", fake_post)

    catalog, glossary, source = propose(manifest, db)
    assert source == "llm"
    assert [(k.name, k.expression) for k in catalog.kpis] == [("Revenue", "SUM(fee)"),
                                                              ("Patients", "COUNT(DISTINCT patient_id)")]
    assert catalog.kpis[0].allowed_dimensions == ["clinic_city"]          # specialty was not kept
    assert "chiffre d'affaires" in glossary.terms[1].synonyms
    assert "M4: SUM(fee)" in sent[0]["messages"][-1]["content"]           # the LLM saw the candidates


def test_works_on_the_olist_dev_warehouse(tmp_path):
    from analysis.dev_warehouse import build
    from contracts.registry import read_output
    build("p1", tmp_path)
    manifest = read_output(tmp_path / "p1/etl/warehouse_manifest.json", "etl.manifest")
    catalog, _, _ = propose(manifest, tmp_path / "p1/etl/warehouse.duckdb", use_llm=False)
    revenue = next(k for k in catalog.kpis if k.expression == "SUM(payment_value)")
    assert "customer_state" in revenue.allowed_dimensions
    assert "COUNT(DISTINCT order_item_id)" not in {k.expression for k in catalog.kpis}   # a line number


def test_approved_kpis_keep_their_name_version_and_filters(tmp_path):
    """Revenue@2.0 of kpi/catalog.yaml is found again: same name, version, unit and filter."""
    from analysis.dev_warehouse import build
    from contracts.registry import read_output
    from contracts.semantic import KpiCatalog, load_yaml
    build("p2", tmp_path)
    manifest = read_output(tmp_path / "p2/etl/warehouse_manifest.json", "etl.manifest")
    approved = load_yaml(KpiCatalog, "kpi/catalog.yaml")
    catalog, glossary, _ = propose(manifest, tmp_path / "p2/etl/warehouse.duckdb", use_llm=False, approved=approved)
    revenue = next(k for k in catalog.kpis if k.expression == "SUM(payment_value)")
    assert revenue.ref == "Revenue@2.0" and revenue.unit == "BRL"
    assert revenue.filters == ["order_status = 'delivered'"]
    assert "product_category" in {d.name for d in catalog.dimensions}      # approved dimension name


def test_no_twin_of_an_approved_kpi_and_one_owner_per_synonym(tmp_path, monkeypatch):
    from analysis.dev_warehouse import build
    from contracts.registry import read_output
    from contracts.semantic import Glossary, KpiCatalog, load_yaml
    build("p3", tmp_path)
    manifest = read_output(tmp_path / "p3/etl/warehouse_manifest.json", "etl.manifest")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    answer = {"kpis": [   # what gpt-oss really answered: a twin of Orders, and "orders" twice
        {"candidate": "M2", "name": "TotalOrders", "description": "Orders.", "unit": "count",
         "synonyms": ["orders", "commandes"]},
        {"candidate": "M3", "name": "UniqueCustomers", "description": "Customers.", "unit": "count",
         "synonyms": ["customers", "orders", "clients", "clients"]}], "dimensions": []}
    sent = []
    monkeypatch.setattr(llm, "_post", lambda url, payload, timeout, headers=None: sent.append(payload) or
                        {"choices": [{"message": {"content": json.dumps(answer)}}]})
    # an approved catalog with only Revenue and Orders (the state of the real one at the time)
    approved = load_yaml(KpiCatalog, "kpi/catalog.yaml")
    approved.kpis = [k for k in approved.kpis if k.name in ("Revenue", "Orders")]
    glossary_ok = load_yaml(Glossary, "semantic/glossary.yaml")
    glossary_ok.terms = [t for t in glossary_ok.terms if t.term in ("Revenue", "Orders", "last month")]
    catalog, glossary, _ = propose(manifest, tmp_path / "p3/etl/warehouse.duckdb",
                                   approved=approved, approved_glossary=glossary_ok)
    names = [k.name for k in catalog.kpis]
    assert "TotalOrders" not in names and {"Revenue", "Orders", "UniqueCustomers"} <= set(names)
    terms = {t.term: t.synonyms for t in glossary.terms}
    assert "commandes" in terms["Orders"]                      # approved synonyms are kept
    assert terms["UniqueCustomers"] == ["customers", "clients"]  # "orders" belongs to Orders; no duplicate
    assert "last month" in terms                              # approved time terms are not lost
    assert "ALREADY APPROVED" in sent[0]["messages"][-1]["content"]
