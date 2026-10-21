"""Step 3: the SQL built from the catalog gives the hand-computed numbers of dev_warehouse.EXPECTED."""
import duckdb
import pytest

from analysis.dev_warehouse import EXPECTED, build
from analysis.sql_compiler import CompileError, compile_query
from contracts.common import Period, load
from contracts.semantic import AnalysisRequest, KpiCatalog, load_yaml
from contracts.warehouse import WarehouseManifest

CATALOG = "contracts/examples/static/kpi/catalog.yaml"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    etl = build("test_run", tmp_path_factory.mktemp("runs"))
    return (duckdb.connect(str(etl / "warehouse.duckdb"), read_only=True),
            load_yaml(KpiCatalog, CATALOG), load(WarehouseManifest, etl / "warehouse_manifest.json"))


def request(**kw):
    base = dict(question="test", metric="Revenue", dimensions=["customer_state"],
                period=Period(start="2018-08-01", end="2018-08-31"),
                compare_to=Period(start="2018-07-01", end="2018-07-31"))
    return AnalysisRequest(**{**base, **kw})


def test_revenue_by_state_matches_hand_computation(env):
    con, catalog, manifest = env
    q = compile_query(request(), catalog, manifest)
    rows = {(s, p): v for s, p, v in con.execute(q.sql).fetchall()}
    assert rows == {("SP", "current"): EXPECTED["2018-08"]["SP"], ("RJ", "current"): EXPECTED["2018-08"]["RJ"],
                    ("SP", "previous"): EXPECTED["2018-07"]["SP"], ("RJ", "previous"): EXPECTED["2018-07"]["RJ"]}


def test_reference_query_gives_the_totals(env):
    con, catalog, manifest = env
    q = compile_query(request(), catalog, manifest)
    assert dict(con.execute(q.reference_sql).fetchall()) == {
        "current": EXPECTED["2018-08"]["total"], "previous": EXPECTED["2018-07"]["total"]}


def test_month_dimension_joins_dim_date(env):
    con, catalog, manifest = env
    q = compile_query(request(dimensions=["order_month"], compare_to=None,
                              period=Period(start="2018-07-01", end="2018-08-31")), catalog, manifest)
    assert dict((m, v) for m, _, v in con.execute(q.sql).fetchall()) == {"2018-07": 300.0, "2018-08": 400.0}


def test_forbidden_dimension_is_refused(env):
    _, catalog, manifest = env
    with pytest.raises(CompileError, match="not allowed"):
        compile_query(request(dimensions=["product_category"]), catalog, manifest)


def test_injected_filter_is_refused(env):
    _, catalog, manifest = env
    with pytest.raises(CompileError):
        compile_query(request(filters=["customer_state = 'SP'; DROP TABLE fact_payments"]), catalog, manifest)


def test_simple_filter_is_applied(env):
    con, catalog, manifest = env
    q = compile_query(request(filters=["customer_state = 'SP'"]), catalog, manifest)
    assert {(s, p) for s, p, _ in con.execute(q.sql).fetchall()} == {("SP", "current"), ("SP", "previous")}


def test_orders_kpi_counts_distinct_orders(env):
    con, catalog, manifest = env
    q = compile_query(request(metric="Orders", dimensions=["product_category"], compare_to=None), catalog, manifest)
    # August delivered: o3 (P1, P2), o5 (P2), o6 (P1, P2, P3)
    assert {c: v for c, _, v in con.execute(q.sql).fetchall()} == {
        "health_beauty": 2, "watches_gifts": 3, "bed_bath_table": 1}


def test_snowflake_join_path_is_found(tmp_path):
    """Snowflake: the state lives in dim_geography, reached through dim_customer (2 hops)."""
    from contracts.semantic import Dimension, KpiDefinition
    from contracts.warehouse import TableKind, WarehouseTable
    con = duckdb.connect()
    con.execute("CREATE TABLE fact_payments AS SELECT * FROM (VALUES ('o1', 1, 'C1', DATE '2018-08-02', 'delivered', 100.0), "
                "('o2', 1, 'C2', DATE '2018-08-05', 'delivered', 50.0)) t(order_id, payment_sequential, customer_id, "
                "order_purchase_date, order_status, payment_value)")
    con.execute("CREATE TABLE dim_customer AS SELECT * FROM (VALUES ('C1', 'G1'), ('C2', 'G2')) t(customer_id, geo_id)")
    con.execute("CREATE TABLE dim_geography AS SELECT * FROM (VALUES ('G1', 'SP'), ('G2', 'RJ')) t(geo_id, customer_state)")
    manifest = WarehouseManifest(tables=[
        WarehouseTable(name="fact_payments", kind=TableKind.FACT, grain="payment", primary_key=["order_id", "payment_sequential"],
                       row_count=2, columns=["order_id", "payment_sequential", "customer_id", "order_purchase_date",
                                             "order_status", "payment_value"], date_column="order_purchase_date"),
        WarehouseTable(name="dim_customer", kind=TableKind.DIMENSION, grain="customer", primary_key=["customer_id"],
                       row_count=2, columns=["customer_id", "geo_id"]),
        WarehouseTable(name="dim_geography", kind=TableKind.DIMENSION, grain="geography", primary_key=["geo_id"],
                       row_count=2, columns=["geo_id", "customer_state"])])
    base = load_yaml(KpiCatalog, CATALOG)
    catalog = KpiCatalog(version="test", kpis=[base.kpi("Revenue")],
                         dimensions=[Dimension(name="customer_state", table="dim_geography",
                                               column="customer_state", description="state")])
    q = compile_query(request(compare_to=None), catalog, manifest)
    assert [j.table for j in q.joins] == ["dim_customer", "dim_geography"]
    assert dict((s, v) for s, _, v in con.execute(q.sql).fetchall()) == {"SP": 100.0, "RJ": 50.0}
