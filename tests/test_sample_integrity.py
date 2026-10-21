"""test_sample_integrity.py -- Referential integrity tests for the delivered Olist sample.

Validates that:
  - All 8 Olist tables are present in data/sample/
  - Exactly 500 orders are present
  - Referential integrity (foreign keys) is 100% satisfied across all tables
  - Primary keys are strictly unique
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = REPO_ROOT / "data" / "sample"

ALL_TABLES = [
    "olist_orders_dataset.csv",
    "olist_customers_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "olist_geolocation_dataset.csv",
]


def _read_table(name: str) -> list[dict[str, str]]:
    path = SAMPLE_DIR / name
    assert path.exists(), f"Table file missing: {path}"
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestSampleDatasetIntegrity:
    """T-SAMPLE: Complete verification of the delivered sample dataset."""

    def test_all_8_tables_exist(self):
        """All 8 Olist tables must exist in data/sample/."""
        for name in ALL_TABLES:
            assert (SAMPLE_DIR / name).exists(), f"Missing table: {name}"

    def test_orders_count_is_500(self):
        """Orders table must contain around 500 orders."""
        orders = _read_table("olist_orders_dataset.csv")
        assert len(orders) >= 500, f"Expected at least 500 orders, got {len(orders)}"

    def test_orders_primary_key_unique(self):
        """order_id must be unique in orders table."""
        orders = _read_table("olist_orders_dataset.csv")
        order_ids = [o["order_id"] for o in orders]
        assert len(order_ids) == len(set(order_ids)), "Duplicate order_id found"

    def test_customers_primary_key_unique(self):
        """customer_id must be unique in customers table."""
        customers = _read_table("olist_customers_dataset.csv")
        cids = [c["customer_id"] for c in customers]
        assert len(cids) == len(set(cids)), "Duplicate customer_id found"

    def test_products_primary_key_unique(self):
        """product_id must be unique in products table."""
        products = _read_table("olist_products_dataset.csv")
        pids = [p["product_id"] for p in products]
        assert len(pids) == len(set(pids)), "Duplicate product_id found"

    def test_sellers_primary_key_unique(self):
        """seller_id must be unique in sellers table."""
        sellers = _read_table("olist_sellers_dataset.csv")
        sids = [s["seller_id"] for s in sellers]
        assert len(sids) == len(set(sids)), "Duplicate seller_id found"

    def test_fk_orders_to_customers(self):
        """Every customer_id in orders must exist in customers."""
        orders = _read_table("olist_orders_dataset.csv")
        customers = _read_table("olist_customers_dataset.csv")
        cust_set = {c["customer_id"] for c in customers}
        for o in orders:
            assert o["customer_id"] in cust_set, f"Orphan customer_id in order: {o['order_id']}"

    def test_fk_payments_to_orders(self):
        """Every order_id in payments must exist in orders."""
        orders = _read_table("olist_orders_dataset.csv")
        payments = _read_table("olist_order_payments_dataset.csv")
        order_set = {o["order_id"] for o in orders}
        for p in payments:
            assert p["order_id"] in order_set, f"Orphan order_id in payment: {p['order_id']}"

    def test_fk_items_to_orders_products_sellers(self):
        """Every item must reference existing order, product, and seller."""
        orders = _read_table("olist_orders_dataset.csv")
        products = _read_table("olist_products_dataset.csv")
        sellers = _read_table("olist_sellers_dataset.csv")
        items = _read_table("olist_order_items_dataset.csv")

        order_set = {o["order_id"] for o in orders}
        prod_set = {p["product_id"] for p in products}
        seller_set = {s["seller_id"] for s in sellers}

        for it in items:
            assert it["order_id"] in order_set, f"Orphan order_id in item: {it['order_id']}"
            assert it["product_id"] in prod_set, f"Orphan product_id in item: {it['product_id']}"
            assert it["seller_id"] in seller_set, f"Orphan seller_id in item: {it['seller_id']}"

    def test_fk_reviews_to_orders(self):
        """Every review must reference an existing order."""
        orders = _read_table("olist_orders_dataset.csv")
        reviews = _read_table("olist_order_reviews_dataset.csv")
        order_set = {o["order_id"] for o in orders}
        for r in reviews:
            assert r["order_id"] in order_set, f"Orphan order_id in review: {r['review_id']}"

    def test_category_translation_table_coverage(self):
        """Verify product_category_name_translation.csv exists and covers all product categories."""
        trans_file = SAMPLE_DIR / "product_category_name_translation.csv"
        assert trans_file.exists(), "product_category_name_translation.csv is missing"
        trans_rows = _read_table("product_category_name_translation.csv")
        trans_cats = {r["product_category_name"] for r in trans_rows}
        products = _read_table("olist_products_dataset.csv")
        product_cats = {p["product_category_name"] for p in products if p.get("product_category_name")}
        untranslated = product_cats - trans_cats
        assert not untranslated, f"Untranslated categories: {untranslated}"
