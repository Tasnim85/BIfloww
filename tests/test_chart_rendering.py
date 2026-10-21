"""tests/test_chart_rendering.py — Tests for chart data preparation and rendering.

Verifies that for every ChartType (kpi_card, bar, line, table):
1. A valid ChartSpec is created.
2. The Parquet data file is correctly parsed.
3. The data format conforms to what Streamlit expects (index, columns, scalar values).
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.dashboard import ChartSpec, ChartType, DashboardSpec


def test_chart_spec_kpi_card(tmp_path):
    """Test data handling for KPI_CARD."""
    df = pd.DataFrame({"revenue": [128450.75]})
    data_file = tmp_path / "kpi.parquet"
    df.to_parquet(data_file)

    spec = ChartSpec(
        chart_id="c_kpi",
        chart_type=ChartType.KPI_CARD,
        title="Total Revenue",
        data_file=str(data_file),
        y="revenue",
        reason="No dimension specified -> KPI card",
    )
    assert spec.chart_type == ChartType.KPI_CARD
    read_df = pd.read_parquet(spec.data_file)
    val = read_df[spec.y].iloc[0]
    assert val == 128450.75


def test_chart_spec_bar_chart(tmp_path):
    """Test data handling for BAR chart."""
    df = pd.DataFrame({
        "customer_state": ["SP", "RJ", "MG"],
        "revenue": [50000.0, 30000.0, 20000.0],
    })
    data_file = tmp_path / "bar.parquet"
    df.to_parquet(data_file)

    spec = ChartSpec(
        chart_id="c_bar",
        chart_type=ChartType.BAR,
        title="Revenue by State",
        data_file=str(data_file),
        x="customer_state",
        y="revenue",
        reason="Categorical dimension -> Bar chart",
    )
    assert spec.chart_type == ChartType.BAR
    read_df = pd.read_parquet(spec.data_file)
    indexed = read_df[[spec.x, spec.y]].set_index(spec.x)
    assert indexed.index.tolist() == ["SP", "RJ", "MG"]
    assert indexed["revenue"].tolist() == [50000.0, 30000.0, 20000.0]


def test_chart_spec_line_chart(tmp_path):
    """Test data handling for LINE chart."""
    df = pd.DataFrame({
        "order_month": ["2018-06", "2018-07", "2018-08"],
        "revenue": [40000.0, 45000.0, 48000.0],
    })
    data_file = tmp_path / "line.parquet"
    df.to_parquet(data_file)

    spec = ChartSpec(
        chart_id="c_line",
        chart_type=ChartType.LINE,
        title="Revenue by Month",
        data_file=str(data_file),
        x="order_month",
        y="revenue",
        reason="Temporal dimension -> Line chart",
    )
    assert spec.chart_type == ChartType.LINE
    read_df = pd.read_parquet(spec.data_file)
    indexed = read_df[[spec.x, spec.y]].set_index(spec.x)
    assert len(indexed) == 3


def test_chart_spec_table(tmp_path):
    """Test data handling for TABLE."""
    df = pd.DataFrame({
        "seller_id": ["s1", "s2"],
        "review_score": [4.5, 4.2],
    })
    data_file = tmp_path / "table.parquet"
    df.to_parquet(data_file)

    spec = ChartSpec(
        chart_id="c_tab",
        chart_type=ChartType.TABLE,
        title="Seller Review Scores",
        data_file=str(data_file),
        reason="Detailed table view",
    )
    assert spec.chart_type == ChartType.TABLE
    read_df = pd.read_parquet(spec.data_file)
    assert "seller_id" in read_df.columns


def test_chart_spec_grouped_bar_chart(tmp_path):
    """Test data handling for grouped BAR chart (2 dimensions: x=state, color=payment_type)."""
    df = pd.DataFrame({
        "customer_state": ["SP", "SP", "RJ", "RJ"],
        "payment_type": ["credit_card", "boleto", "credit_card", "boleto"],
        "revenue": [35000.0, 15000.0, 20000.0, 10000.0],
    })
    data_file = tmp_path / "grouped_bar.parquet"
    df.to_parquet(data_file)

    spec = ChartSpec(
        chart_id="c_grouped_bar",
        chart_type=ChartType.BAR,
        title="Revenue by State and Payment Type",
        data_file=str(data_file),
        x="customer_state",
        y="revenue",
        color="payment_type",
        reason="Automatic selection: grouped bar across customer_state, payment_type",
    )
    assert spec.chart_type == ChartType.BAR
    assert spec.color == "payment_type"
    read_df = pd.read_parquet(spec.data_file)
    # Streamlit uses df with x, y, and color directly in st.bar_chart(df, x=x, y=y, color=color)
    assert spec.x in read_df.columns
    assert spec.y in read_df.columns
    assert spec.color in read_df.columns
    pivoted = read_df.pivot(index=spec.x, columns=spec.color, values=spec.y)
    assert pivoted.shape == (2, 2)
    assert pivoted.loc["SP", "credit_card"] == 35000.0

