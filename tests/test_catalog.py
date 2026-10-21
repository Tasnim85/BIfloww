"""The real KPI catalog and glossary (kpi/catalog.yaml, semantic/glossary.yaml).
Every KPI, on every dimension it allows, must compile, run and pass the BO3-03 checks;
the new KPIs are checked against values computed BY HAND on the dev warehouse."""
import duckdb
import pytest

from analysis.dev_warehouse import build
from analysis.sql_compiler import compile_query
from analysis.validations import run_checks
from contracts.common import Period
from contracts.registry import read_output
from contracts.semantic import AnalysisRequest, Glossary, KpiCatalog, load_yaml

CATALOG = load_yaml(KpiCatalog, "kpi/catalog.yaml")
GLOSSARY = load_yaml(Glossary, "semantic/glossary.yaml")
AUGUST, JULY = Period(start="2018-08-01", end="2018-08-31"), Period(start="2018-07-01", end="2018-07-31")


@pytest.fixture(scope="module")
def dev(tmp_path_factory):
    root = tmp_path_factory.mktemp("cat")
    build("c1", root)
    etl = root / "c1/etl"
    return (duckdb.connect(str(etl / "warehouse.duckdb"), read_only=True),
            read_output(etl / "warehouse_manifest.json", "etl.manifest"),
            read_output(etl / "receipts.json", "etl.receipts"))


def compute(dev, metric, dims=()):
    con, manifest, receipts = dev
    q = compile_query(AnalysisRequest(question="t", metric=metric, dimensions=list(dims),
                                      period=AUGUST, compare_to=JULY), CATALOG, manifest)
    df = con.execute(q.sql).df()
    totals = df.groupby("period")["value"].sum().to_dict()
    return df, run_checks(con, q, manifest, receipts, totals)


@pytest.mark.parametrize("kpi,dim", [(k.name, d) for k in CATALOG.kpis for d in [None] + k.allowed_dimensions])
def test_every_kpi_runs_and_passes_bo3_03(dev, kpi, dim):
    _, checks = compute(dev, kpi, [dim] if dim else [])
    assert all(c.passed for c in checks), [c.detail for c in checks if not c.passed]


# Hand values, August (o3, o5, o6 delivered; o4 canceled) vs July (o1, o2):
@pytest.mark.parametrize("kpi,august,july", [
    ("Customers", 3, 2),                   # C3, C1, C2  |  C1, C2
    ("ItemsSold", 6, 3),                   # o3: 2, o5: 1, o6: 3  |  o1: 2, o2: 1
    ("Freight", 45.0, 35.0),               # 15+5+10+5+5+5  |  10+5+20
    ("AverageBasket", 133.33, 150.0),      # 400 / 3 orders  |  300 / 2 orders
])
def test_new_kpis_match_hand_values(dev, kpi, august, july):
    df, _ = compute(dev, kpi)
    values = dict(zip(df["period"], df["value"]))
    assert round(values["current"], 2) == august and round(values["previous"], 2) == july


def test_glossary_matches_the_catalog():
    names = {k.name for k in CATALOG.kpis} | {d.name for d in CATALOG.dimensions}
    for t in GLOSSARY.terms:
        assert t.kind == "time" or t.term in names, f"{t.term} is not in the catalog"
    assert names <= {t.term for t in GLOSSARY.terms}, "a KPI or dimension has no glossary entry"
    words = [s.lower() for t in GLOSSARY.terms for s in [t.term] + t.synonyms]
    assert len(words) == len(set(words)), "a synonym belongs to two terms"
