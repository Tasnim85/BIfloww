"""The lineage step links the KPIs of kpi/catalog.yaml to the analytic views of the warehouse.

The catalog names the contract views (fact_payments, dim_date...); the lineage reads them from
the shared manifest, as contracts/pipeline.py wires the step (receipts, manifest, catalog).
"""
from pathlib import Path

from contracts import AgentStatus, context_for
from contracts.registry import read_output
from contracts.semantic import KpiCatalog, load_yaml
from etl.lineage import run
from tests.test_analytic_views import build_warehouse

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_every_catalog_kpi_is_traced_to_a_cleaned_column(tmp_path):
    build_warehouse(tmp_path / "t1", "star")
    ctx = context_for("lineage", "t1", runs_root=tmp_path, journal=tmp_path / "t1" / "audit_journal.db",
                      params={"backend": "json"})
    result = run(ctx)
    assert result.status == AgentStatus.SUCCESS, result.message

    graph = read_output(result.outputs["graph"], "lineage.graph")
    edges = {(e.source, e.target) for e in graph.edges}     # valid against the contract (LineageGraph)
    catalog = load_yaml(KpiCatalog, REPO_ROOT / "kpi/catalog.yaml")
    for kpi in catalog.kpis:
        assert any(target == f"kpi:{kpi.ref}" for _, target in edges), kpi.ref
    # Revenue = SUM(payment_value) on fact_payments, which comes from the cleaned payments table.
    assert ("warehouse:fact_payments.payment_value", "kpi:Revenue@2.0") in edges
    assert ("clean:olist_order_payments_dataset.payment_value", "warehouse:fact_payments.payment_value") in edges
