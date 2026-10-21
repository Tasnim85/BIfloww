"""Tests for Step 2 — Schema Reader.

Owner: Samar / Malek (Step 2)
"""
from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from intake.semantic_detection.step2.schema_reader import (
    ColumnSchema,
    TableSchema,
    read_csv_schema,
    read_json_schema,
    read_schema_dir,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_csv(tmp_path: Path) -> Path:
    """Create a small CSV file."""
    p = tmp_path / "orders.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["order_id", "customer_id", "price", "order_date", "status"])
        writer.writerow(["ORD-001", "CUST-1", "29.99", "2026-01-15", "delivered"])
        writer.writerow(["ORD-002", "CUST-2", "15.00", "2026-01-16", "shipped"])
    return p


@pytest.fixture()
def tmp_json_flavour_a(tmp_path: Path) -> Path:
    """Flavour A: list of column dicts."""
    p = tmp_path / "products.json"
    data = [
        {"column": "product_id", "type": "string", "nullable": False},
        {"column": "price", "type": "float", "nullable": True, "samples": [9.99, 14.99]},
        {"column": "category", "type": "string"},
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def tmp_json_flavour_b(tmp_path: Path) -> Path:
    """Flavour B: dict with 'columns' key."""
    p = tmp_path / "customers.json"
    data = {
        "table": "customers",
        "source": "CRM",
        "columns": [
            {"name": "customer_id", "dtype": "string"},
            {"name": "email", "dtype": "string", "nullable": False},
            {"name": "age", "dtype": "int"},
        ],
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def tmp_json_flavour_c(tmp_path: Path) -> Path:
    """Flavour C: simple list of column names."""
    p = tmp_path / "simple.json"
    p.write_text(json.dumps(["col_a", "col_b", "col_c"]), encoding="utf-8")
    return p


# ── CSV tests ──────────────────────────────────────────────────────────────────

class TestReadCsvSchema:

    def test_returns_table_schema(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        assert isinstance(ts, TableSchema)

    def test_table_name_from_stem(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        assert ts.table == "orders"

    def test_column_count(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        assert len(ts.columns) == 5

    def test_column_names(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        assert ts.column_names == ["order_id", "customer_id", "price", "order_date", "status"]

    def test_column_positions(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        for i, col in enumerate(ts.columns):
            assert col.position == i

    def test_sample_values_populated(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        price_col = next(c for c in ts.columns if c.column == "price")
        assert "29.99" in price_col.sample_values

    def test_row_count_hint(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        assert ts.row_count_hint == 2

    def test_source_format_csv(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        assert ts.source_format == "csv"
        assert all(c.source_format == "csv" for c in ts.columns)

    def test_declared_type_none_for_csv(self, tmp_csv: Path) -> None:
        ts = read_csv_schema(tmp_csv)
        assert all(c.declared_type is None for c in ts.columns)

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_csv_schema(tmp_path / "nonexistent.csv")

    def test_empty_csv_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            read_csv_schema(p)


# ── JSON tests ─────────────────────────────────────────────────────────────────

class TestReadJsonSchema:

    def test_flavour_a_column_count(self, tmp_json_flavour_a: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_a)
        assert len(ts.columns) == 3

    def test_flavour_a_column_names(self, tmp_json_flavour_a: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_a)
        assert ts.column_names == ["product_id", "price", "category"]

    def test_flavour_a_declared_type(self, tmp_json_flavour_a: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_a)
        price = next(c for c in ts.columns if c.column == "price")
        assert price.declared_type == "float"

    def test_flavour_a_nullable(self, tmp_json_flavour_a: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_a)
        pid = next(c for c in ts.columns if c.column == "product_id")
        assert pid.nullable is False

    def test_flavour_a_samples(self, tmp_json_flavour_a: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_a)
        price = next(c for c in ts.columns if c.column == "price")
        assert 9.99 in price.sample_values

    def test_flavour_b_table_name(self, tmp_json_flavour_b: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_b)
        assert ts.table == "customers"

    def test_flavour_b_column_count(self, tmp_json_flavour_b: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_b)
        assert len(ts.columns) == 3

    def test_flavour_b_declared_type(self, tmp_json_flavour_b: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_b)
        age = next(c for c in ts.columns if c.column == "age")
        assert age.declared_type == "int"

    def test_flavour_c_simple_list(self, tmp_json_flavour_c: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_c)
        assert ts.column_names == ["col_a", "col_b", "col_c"]

    def test_flavour_c_table_name_override(self, tmp_json_flavour_c: Path) -> None:
        ts = read_json_schema(tmp_json_flavour_c, table_name="my_table")
        assert ts.table == "my_table"

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_json_schema(tmp_path / "nope.json")

    def test_invalid_json_structure(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        with pytest.raises(ValueError):
            read_json_schema(p)


# ── Directory reader tests ─────────────────────────────────────────────────────

class TestReadSchemaDir:

    def test_reads_csv_and_json(self, tmp_path: Path, tmp_csv: Path, tmp_json_flavour_a: Path) -> None:
        # tmp_csv and tmp_json_flavour_a are already in tmp_path
        results = read_schema_dir(tmp_path)
        names = {ts.table for ts in results}
        assert "orders" in names
        assert "products" in names

    def test_empty_directory(self, tmp_path: Path) -> None:
        results = read_schema_dir(tmp_path)
        assert results == []

    def test_not_a_directory(self, tmp_csv: Path) -> None:
        with pytest.raises(NotADirectoryError):
            read_schema_dir(tmp_csv)
