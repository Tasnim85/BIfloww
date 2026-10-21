"""Step 4: the BO3-03 checks pass on the correct query and catch the payments x items trap."""
import duckdb
import pytest

from analysis.dev_warehouse import EXPECTED, build
from analysis.sql_compiler import Join, compile_query
from analysis.validations import run_checks
from contracts.common import Period, load
from contracts.semantic import AnalysisRequest, KpiCatalog, load_yaml
from contracts.warehouse import TransformationReceipts, WarehouseManifest

CATALOG = "contracts/examples/static/kpi/catalog.yaml"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    etl = build("test_run", tmp_path_factory.mktemp("runs"))
    return (duckdb.connect(str(etl / "warehouse.duckdb"), read_only=True), load_yaml(KpiCatalog, CATALOG),
            load(WarehouseManifest, etl / "warehouse_manifest.json"),
            load(TransformationReceipts, etl / "receipts.json"))


def request(**kw):
    base = dict(question="test", metric="Revenue", dimensions=["customer_state"],
                period=Period(start="2018-08-01", end="2018-08-31"),
                compare_to=Period(start="2018-07-01", end="2018-07-31"))
    return AnalysisRequest(**{**base, **kw})


def totals_of(con, q):
    out = {}
    for *_, period, value in con.execute(q.sql).fetchall():
        out[period] = out.get(period, 0.0) + value
    return out


def test_correct_query_passes_every_check(env):
    con, catalog, manifest, receipts = env
    q = compile_query(request(), catalog, manifest)
    checks = run_checks(con, q, manifest, receipts, totals_of(con, q))
    assert {c.name: c.passed for c in checks} == {
        "grain_matches_kpi": True, "join_multiplicity": True, "reference_value": True, "etl_receipt": True}


def test_join_to_order_items_is_caught(env):
    """The BO3-03 trap: someone joins payments to items. Revenue becomes 840 instead of 400."""
    con, catalog, manifest, receipts = env
    q = compile_query(request(compare_to=None), catalog, manifest)
    bad = Join("fact_order_items", "x", "f.order_id = x.order_id")
    q.joins.append(bad)
    trap = f" JOIN {bad.table} {bad.alias} ON {bad.on}"
    q.sql = q.sql.replace(" WHERE ", trap + " WHERE ", 1)
    q.joined_count_sql = q.joined_count_sql.replace(" WHERE ", trap + " WHERE ", 1)
    totals = totals_of(con, q)
    assert totals["current"] == EXPECTED["2018-08 if payments were joined to items"]   # 840, not 400

    checks = {c.name: c for c in run_checks(con, q, manifest, receipts, totals)}
    assert not checks["join_multiplicity"].passed
    assert "4 rows were duplicated" in checks["join_multiplicity"].detail      # 4 delivered August payments -> 8 rows
    assert not checks["reference_value"].passed
    assert "840.00 vs reference 400.00" in checks["reference_value"].detail


def test_wrong_grain_is_caught(env):
    con, catalog, manifest, receipts = env
    q = compile_query(request(), catalog, manifest)
    q.kpi = q.kpi.model_copy(update={"grain": "order"})
    checks = {c.name: c for c in run_checks(con, q, manifest, receipts, totals_of(con, q))}
    assert not checks["grain_matches_kpi"].passed


def test_fan_out_in_etl_receipt_is_caught(env):
    con, catalog, manifest, receipts = env
    q = compile_query(request(), catalog, manifest)
    bad = receipts.model_copy(deep=True)
    bad.receipts[0].rows_after = 12
    checks = {c.name: c for c in run_checks(con, q, manifest, bad, totals_of(con, q))}
    assert not checks["etl_receipt"].passed
    assert "duplicated rows" in checks["etl_receipt"].detail
