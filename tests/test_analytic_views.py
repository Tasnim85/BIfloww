"""The shared manifest lists analytical views the Analyst can join (etl/analytics.py).

Runs etl.build:run on a small Olist-shaped dataset, with a hand-written plan instead of Llama3.
"""
import json
import random

import duckdb
import pandas as pd
import pytest

from contracts import AgentStatus, RunContext
from contracts.registry import read_output
from etl.generic import inventory, relationships, digest
from etl.dimensional_design import profile, Plan, Role, validate
import etl.build


def build_warehouse(root, layout, orders_role="fact"):
    tables = root / "cleaning" / "tables"; tables.mkdir(parents=True)
    random.seed(1)
    states = ["SP", "RJ", "MG"]; cats = ["beleza_saude", "esporte_lazer", "informatica"]
    customers = pd.DataFrame({"customer_id": [f"c{i}" for i in range(30)], "customer_unique_id": [f"u{i}" for i in range(30)],
                              "customer_state": [random.choice(states) for _ in range(30)]})
    sellers = pd.DataFrame({"seller_id": [f"s{i}" for i in range(5)], "seller_state": [random.choice(states) for _ in range(5)]})
    products = pd.DataFrame({"product_id": [f"p{i}" for i in range(12)], "product_category_name": [cats[i % 3] for i in range(12)],
                             "product_weight_g": [100.0 * (i + 1) for i in range(12)]})
    translation = pd.DataFrame({"product_category_name": cats, "product_category_name_english": ["health_beauty", "sports_leisure", "computers"]})
    orders = pd.DataFrame({"order_id": [f"o{i}" for i in range(60)], "customer_id": [f"c{i % 30}" for i in range(60)],
                           "order_status": ["delivered" if i % 7 else "canceled" for i in range(60)],
                           "order_purchase_timestamp": [f"2018-0{7 + i % 2}-{1 + i % 28:02d} 10:00:00" for i in range(60)]})
    items = pd.DataFrame([{"order_id": f"o{i}", "order_item_id": k + 1, "product_id": f"p{(i + k) % 12}", "seller_id": f"s{i % 5}",
                           "shipping_limit_date": f"2018-09-{1 + i % 28:02d} 00:00:00", "price": round(10 + i * 1.5, 2), "freight_value": 5.25}
                          for i in range(60) for k in range(1 + i % 2)])
    payments = pd.DataFrame([{"order_id": f"o{i}", "payment_sequential": k + 1, "payment_type": ["credit_card", "boleto", "voucher"][(i + k) % 3],
                              "payment_value": round(20 + i * 2.0 - k * 5, 2)} for i in range(60) for k in range(1 + (i % 5 == 0))])
    for name, frame in {"olist_customers_dataset": customers, "olist_sellers_dataset": sellers, "olist_products_dataset": products,
                        "product_category_name_translation": translation, "olist_orders_dataset": orders,
                        "olist_order_items_dataset": items, "olist_order_payments_dataset": payments}.items():
        frame.to_parquet(tables / f"{name}.parquet", index=False)
    (root / "cleaning" / "cleaning_report.json").write_text(json.dumps({"needs_review": []}))

    out = root / "etl"; out.mkdir()
    ctx = RunContext(run_id="t1", agent="etl", inputs={"tables": tables, "cleaning_report": root / "cleaning" / "cleaning_report.json"},
                     output_dir=out, params={}, journal=root / "audit_journal.db")
    frames, metadata, hashes = inventory(ctx); profiles = profile(frames, metadata); candidates = relationships(frames, metadata)
    by_source = {m["source"]: t for t, m in metadata.items()}
    def role(src, r, grain, **kw):
        return Role(table=by_source[src], role=r, grain=grain, reason="test", **kw)
    roles = [role("olist_customers_dataset", "dimension", "client"), role("olist_sellers_dataset", "dimension", "vendeur"),
             role("olist_products_dataset", "dimension", "produit"), role("product_category_name_translation", "reference", "traduction"),
             role("olist_orders_dataset", orders_role, "commande", dates=["order_purchase_timestamp"] if orders_role == "fact" else []),
             role("olist_order_items_dataset", "fact", "article", measures=["price", "freight_value"], dates=["shipping_limit_date"]),
             role("olist_order_payments_dataset", "fact", "paiement", measures=["payment_value"])]
    plan = Plan(schema_type=layout, rationale="test", tables=roles, relationships=[c["id"] for c in candidates])
    validate(plan, profiles, candidates)
    proposal = out / "warehouse_proposal.json"
    proposal.write_text(json.dumps({"version": 2, "cleaning_source": str(tables.parent.resolve()), "source_fingerprints": hashes,
        "tables": metadata, "profiles": profiles, "candidates": candidates, "design": plan.model_dump()}, ensure_ascii=False, indent=2))
    ctx = ctx.model_copy(update={"params": {"etl_approval": digest(proposal)}})
    result = etl.build.run(ctx)
    assert result.status == AgentStatus.SUCCESS, result.message
    return out


# Llama3 may call the orders a fact (an event) or a dimension (it describes the payments): same views.
@pytest.mark.parametrize("layout,orders_role", [("star", "fact"), ("constellation", "fact"), ("snowflake", "fact"),
                                                ("constellation", "dimension")])
def test_manifest_lists_views_the_analyst_can_join(tmp_path, layout, orders_role):
    out = build_warehouse(tmp_path, layout, orders_role)
    manifest = read_output(out / "warehouse_manifest.json", "etl.manifest")
    receipts = read_output(out / "receipts.json", "etl.receipts")
    tables = {t.name: t for t in manifest.tables}
    assert {"fact_payments", "fact_order_items", "dim_customer", "dim_product", "dim_seller", "dim_date"} <= set(tables)
    assert {r.output_table for r in receipts.receipts} == set(tables)
    # The names, grains and keys agreed in contracts/examples (README section 9).
    example = read_output("contracts/examples/run_001/etl/warehouse_manifest.json", "etl.manifest")
    for agreed in example.tables:
        mine = tables[agreed.name]
        assert (mine.kind, mine.grain, mine.primary_key, mine.date_column) == \
               (agreed.kind, agreed.grain, agreed.primary_key, agreed.date_column), agreed.name

    pay = tables["fact_payments"]
    # Rule 1: the fact carries the natural key of each dimension (customer_id comes from orders).
    assert {"customer_id", "order_status", "payment_value"} <= set(pay.columns)
    # Rule 2: a DATE column, declared in the manifest.
    assert pay.date_column == "order_purchase_date" and pay.date_min == "2018-07-01"
    # Rule 3: the calendar is keyed by date, grain day, with year_month.
    cal = tables["dim_date"]
    assert cal.grain == "day" and cal.primary_key == ["date"] and "year_month" in cal.columns
    # The reference table translates the category inside the product dimension.
    assert "product_category_name_english" in tables["dim_product"].columns

    con = duckdb.connect(str(out / "warehouse.duckdb"), read_only=True)
    try:
        rows = con.execute("SELECT c.customer_state, SUM(f.payment_value) FROM fact_payments f "
                           "JOIN dim_customer c ON f.customer_id = c.customer_id "
                           "JOIN dim_date d ON f.order_purchase_date = d.date "
                           "WHERE d.year_month = '2018-08' GROUP BY 1").fetchall()
        total = con.execute("SELECT SUM(payment_value) FROM fact_payments WHERE order_purchase_date >= '2018-08-01'").fetchone()[0]
        assert sum(v for _, v in rows) == pytest.approx(total)      # the joins do not multiply rows
        assert con.execute("SELECT count(*) FROM fact_payments").fetchone()[0] == pay.row_count
    finally:
        con.close()
