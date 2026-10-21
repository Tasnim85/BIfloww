"""TEMPORARY: a tiny warehouse to develop the Analyst before Ahmed's ETL exists.

It writes exactly what the real ETL step writes, with the same contracts:
    runs/<run_id>/etl/warehouse.duckdb
    runs/<run_id>/etl/warehouse_manifest.json
    runs/<run_id>/etl/receipts.json
and copies the example request into runs/<run_id>/request/.

The data is small enough to check by hand (see EXPECTED below).
When Ahmed's real warehouse is ready, delete this file: the Analyst does not change.

    python -m analysis.dev_warehouse            # builds runs/dev_001/
"""
import shutil
from pathlib import Path

import duckdb

from contracts import save
from contracts.pipeline import RUNS_ROOT, STEPS
from contracts.warehouse import (TableKind, TransformationReceipt, TransformationReceipts,
                                 WarehouseManifest, WarehouseTable)

EXAMPLE_REQUEST = Path(__file__).resolve().parent.parent / "contracts/examples/run_001/request/analysis_request.json"

# ---- Raw rows (order_id, customer_id, purchase date, status) ----------------------------
CUSTOMERS = [("C1", "U1", "sao paulo", "SP"), ("C2", "U2", "rio de janeiro", "RJ"),
             ("C3", "U3", "campinas", "SP"), ("C4", "U4", "belo horizonte", "MG")]
ORDERS = [("o1", "C1", "2018-07-05", "delivered"), ("o2", "C2", "2018-07-20", "delivered"),
          ("o3", "C3", "2018-08-03", "delivered"), ("o4", "C4", "2018-08-10", "canceled"),
          ("o5", "C1", "2018-08-15", "delivered"), ("o6", "C2", "2018-08-29", "delivered")]
# (order_id, payment_sequential, payment_type, installments, payment_value)
# o3 is paid in TWO payments: that is why Revenue is computed at payment grain.
PAYMENTS = [("o1", 1, "credit_card", 1, 100.0), ("o2", 1, "boleto", 1, 200.0),
            ("o3", 1, "credit_card", 2, 150.0), ("o3", 2, "voucher", 1, 50.0),
            ("o4", 1, "credit_card", 1, 300.0), ("o5", 1, "debit_card", 1, 80.0),
            ("o6", 1, "credit_card", 3, 120.0)]
# (order_id, order_item_id, product_id, seller_id, price, freight_value)
# Several items per order: joining payments to items would DUPLICATE payment_value.
ITEMS = [("o1", 1, "P1", "S1", 60.0, 10.0), ("o1", 2, "P2", "S1", 25.0, 5.0),
         ("o2", 1, "P3", "S2", 180.0, 20.0),
         ("o3", 1, "P1", "S1", 120.0, 15.0), ("o3", 2, "P2", "S2", 60.0, 5.0),
         ("o4", 1, "P3", "S2", 280.0, 20.0),
         ("o5", 1, "P2", "S1", 70.0, 10.0),
         ("o6", 1, "P1", "S1", 50.0, 5.0), ("o6", 2, "P2", "S2", 40.0, 5.0), ("o6", 3, "P3", "S2", 15.0, 5.0)]
PRODUCTS = [("P1", "health_beauty", 500), ("P2", "watches_gifts", 200), ("P3", "bed_bath_table", 1500)]
SELLERS = [("S1", "sao paulo", "SP"), ("S2", "curitiba", "PR")]

# Revenue@2.0 = SUM(payment_value) of delivered orders, computed by hand:
EXPECTED = {
    "2018-07": {"SP": 100.0, "RJ": 200.0, "total": 300.0},
    "2018-08": {"SP": 280.0, "RJ": 120.0, "total": 400.0},   # SP = o3 (150+50) + o5 (80); o4 is canceled
    "2018-08 if payments were joined to items": 840.0,          # the BO3-03 trap: o3 x2, o6 x3
}


def build(run_id: str = "dev_001", runs_root: Path = RUNS_ROOT) -> Path:
    etl_dir = Path(runs_root) / run_id / "etl"
    etl_dir.mkdir(parents=True, exist_ok=True)
    db_path = etl_dir / STEPS["etl"].outputs["warehouse"]
    db_path.unlink(missing_ok=True)

    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE orders (order_id VARCHAR, customer_id VARCHAR, order_purchase_date DATE, order_status VARCHAR)")
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", ORDERS)
    con.execute("CREATE TABLE order_payments (order_id VARCHAR, payment_sequential INT, payment_type VARCHAR, payment_installments INT, payment_value DOUBLE)")
    con.executemany("INSERT INTO order_payments VALUES (?, ?, ?, ?, ?)", PAYMENTS)
    con.execute("CREATE TABLE order_items (order_id VARCHAR, order_item_id INT, product_id VARCHAR, seller_id VARCHAR, price DOUBLE, freight_value DOUBLE)")
    con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?)", ITEMS)

    # Star schema, same tables and columns as the example manifest.
    con.execute("""CREATE TABLE fact_payments AS
        SELECT p.order_id, p.payment_sequential, p.payment_type, p.payment_installments, p.payment_value,
               o.customer_id, o.order_purchase_date, o.order_status
        FROM order_payments p JOIN orders o USING (order_id)
        WHERE o.order_status = 'delivered'""")
    con.execute("""CREATE TABLE fact_order_items AS
        SELECT i.order_id, i.order_item_id, i.product_id, i.seller_id, i.price, i.freight_value,
               o.customer_id, o.order_purchase_date, o.order_status
        FROM order_items i JOIN orders o USING (order_id)
        WHERE o.order_status = 'delivered'""")
    con.execute("CREATE TABLE dim_customer (customer_id VARCHAR, customer_unique_id VARCHAR, customer_city VARCHAR, customer_state VARCHAR)")
    con.executemany("INSERT INTO dim_customer VALUES (?, ?, ?, ?)", CUSTOMERS)
    con.execute("CREATE TABLE dim_product (product_id VARCHAR, product_category_name_english VARCHAR, product_weight_g INT)")
    con.executemany("INSERT INTO dim_product VALUES (?, ?, ?)", PRODUCTS)
    con.execute("CREATE TABLE dim_seller (seller_id VARCHAR, seller_city VARCHAR, seller_state VARCHAR)")
    con.executemany("INSERT INTO dim_seller VALUES (?, ?, ?)", SELLERS)
    con.execute("""CREATE TABLE dim_date AS
        SELECT d::DATE AS date, year(d) AS year, month(d) AS month,
               strftime(d, '%Y-%m') AS year_month, dayname(d) AS weekday
        FROM range(DATE '2018-07-01', DATE '2018-09-01', INTERVAL 1 DAY) t(d)""")
    con.execute("DROP TABLE orders; DROP TABLE order_payments; DROP TABLE order_items")

    def table(name, kind, grain, pk, date_column=None):
        cols = [r[0] for r in con.execute(f"DESCRIBE {name}").fetchall()]
        rows = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        dmin = dmax = None
        if date_column:
            dmin, dmax = (str(v) for v in con.execute(
                f"SELECT MIN({date_column}), MAX({date_column}) FROM {name}").fetchone())
        return WarehouseTable(name=name, kind=kind, grain=grain, primary_key=pk, row_count=rows,
                              columns=cols, date_column=date_column, date_min=dmin, date_max=dmax)

    manifest = WarehouseManifest(tables=[
        table("fact_payments", TableKind.FACT, "payment", ["order_id", "payment_sequential"], "order_purchase_date"),
        table("fact_order_items", TableKind.FACT, "order_item", ["order_id", "order_item_id"], "order_purchase_date"),
        table("dim_customer", TableKind.DIMENSION, "customer", ["customer_id"]),
        table("dim_product", TableKind.DIMENSION, "product", ["product_id"]),
        table("dim_seller", TableKind.DIMENSION, "seller", ["seller_id"]),
        table("dim_date", TableKind.DIMENSION, "day", ["date"]),
    ])
    con.close()

    delivered_payments = sum(1 for p in PAYMENTS if dict((o[0], o[3]) for o in ORDERS)[p[0]] == "delivered")
    delivered_items = sum(1 for i in ITEMS if dict((o[0], o[3]) for o in ORDERS)[i[0]] == "delivered")
    receipts = TransformationReceipts(receipts=[
        TransformationReceipt(
            output_table="fact_payments", source_tables=["order_payments", "orders"], join_keys=["order_id"],
            rows_before=len(PAYMENTS), rows_after=delivered_payments, grain="payment",
            filters=["order_status == 'delivered'"],
            column_sources={"payment_value": "order_payments.payment_value",
                            "order_purchase_date": "orders.order_purchase_timestamp",
                            "order_status": "orders.order_status"}),
        TransformationReceipt(
            output_table="fact_order_items", source_tables=["order_items", "orders"], join_keys=["order_id"],
            rows_before=len(ITEMS), rows_after=delivered_items, grain="order_item",
            filters=["order_status == 'delivered'"],
            column_sources={"price": "order_items.price",
                            "order_purchase_date": "orders.order_purchase_timestamp"}),
    ])
    save(manifest, etl_dir / STEPS["etl"].outputs["manifest"])
    save(receipts, etl_dir / STEPS["etl"].outputs["receipts"])

    request_dir = Path(runs_root) / run_id / "request"
    request_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(EXAMPLE_REQUEST, request_dir / STEPS["request"].outputs["request"])
    return etl_dir


if __name__ == "__main__":
    out = build()
    con = duckdb.connect(str(out / "warehouse.duckdb"), read_only=True)
    for name, rows in con.execute("SELECT table_name, estimated_size FROM duckdb_tables() ORDER BY 1").fetchall():
        print(f"  {name:<18} {con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]} rows")
    aug = con.execute("""SELECT SUM(payment_value) FROM fact_payments
                         WHERE order_purchase_date BETWEEN '2018-08-01' AND '2018-08-31'""").fetchone()[0]
    print(f"Built {out}. Revenue August 2018 = {aug} (expected {EXPECTED['2018-08']['total']})")
