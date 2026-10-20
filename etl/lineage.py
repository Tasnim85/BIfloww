"""Ahmed: file/column lineage from ETL receipts without reopening raw data."""
import json

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.artifacts import TransformationReceipt
from contracts.audit import AuditEvent, log_event
from .models import LineageReport, WarehouseManifest


def run(ctx: RunContext) -> AgentResult:
    outputs = {}
    try:
        if ctx.agent != "lineage":
            raise ValueError("Expected agent='lineage'")
        receipts = [TransformationReceipt.model_validate(item) for item in json.loads(ctx.inputs["receipts"].read_text(encoding="utf-8"))]
        manifest = WarehouseManifest.model_validate_json(ctx.inputs["manifest"].read_text(encoding="utf-8")).model_dump()
        nodes = {}
        edges = []

        def connect(source, target, operation):
            for node in [source, target]:
                nodes[node] = {"id": node, "kind": node.split(":", 1)[0]}
            edges.append({"source": source, "target": target, "operation": operation})

        for receipt in receipts:
            if receipt.output_table not in manifest["tables"]:
                # Physical transformation receipts are represented by the column mappings.
                continue
            for column in manifest["tables"][receipt.output_table]["columns"]:
                col = column["name"]
                storage = manifest["tables"][receipt.output_table]["physical_sources"].get(col, [])
                targets = [f"physical:{location}" for location in storage] or [f"warehouse:{receipt.output_table}.{col}"]
                if receipt.output_table == "dim_date":
                    source_table, source_column = "orders", "order_purchase_timestamp"
                    # Calendar also spans approval, delivery and estimated dates.
                    for date_col in ["order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"]:
                        connect(f"raw:orders.{date_col}", f"pii:orders.{date_col}", "privacy_policy")
                        connect(f"pii:orders.{date_col}", f"clean:orders.{date_col}", "approved_cleaning")
                        for target in targets:
                            connect(f"clean:orders.{date_col}", target, "calendar_range")
                else:
                    source_table = receipt.source_tables[0]
                    source_column = col
                    if receipt.output_table.startswith("fact_") and col in {"customer_id", "order_status", "order_purchase_timestamp", "order_delivered_customer_date", "purchase_date_key"}:
                        source_table = "orders"
                        if col == "purchase_date_key":
                            source_column = "order_purchase_timestamp"
                raw = f"raw:{source_table}.{source_column}"
                masked = f"pii:{source_table}.{source_column}"
                cleaned = f"clean:{source_table}.{source_column}"
                target = f"warehouse:{receipt.output_table}.{col}"
                connect(raw, masked, "privacy_policy")
                connect(masked, cleaned, "approved_cleaning")
                for physical_target in targets:
                    connect(cleaned, physical_target, "calendar" if receipt.output_table == "dim_date" else "etl")
                    if physical_target != target:
                        connect(physical_target, target, "canonical_table_or_view")
                    if receipt.join_keys:
                        connect(f"transformation:{receipt.output_table}", physical_target, "join_dependency")
            for key in receipt.join_keys:
                for source in receipt.source_tables:
                    connect(f"clean:{source}.{key}", f"transformation:{receipt.output_table}", "join_dependency")
        # A catalog owner supplies validated bindings; this default is only a demo trace.
        bindings = ctx.params.get("metric_sources", {"Revenue_demo": {"table": "fact_payments", "column": "payment_value"}})
        for metric, binding in bindings.items():
            table, column = binding["table"], binding["column"]
            if table not in manifest["tables"] or column not in {x["name"] for x in manifest["tables"][table]["columns"]}:
                raise ValueError("Invalid metric source binding")
            connect(f"warehouse:{table}.{column}", f"kpi:{metric}", "catalog_binding" if "metric_sources" in ctx.params else "demo_binding_pending_Rabeb_catalog")
        # Deduplicate edges because a calendar is derived from several dates.
        edges = list({(e["source"], e["target"], e["operation"]): e for e in edges}.values())
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.output_dir / "lineage.json"
        graph = LineageReport(nodes=list(nodes.values()), edges=edges)
        path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
        outputs["lineage"] = path
        backend = ctx.params.get("backend", "neo4j")
        if backend == "neo4j":
            from .neo4j_store import import_graph
            report = import_graph(graph, ctx.run_id)
            imported = ctx.output_dir / "neo4j_import.json"
            imported.write_text(json.dumps(report, indent=2), encoding="utf-8")
            outputs["neo4j_import"] = imported
        elif backend != "json":
            raise ValueError("Lineage backend must be neo4j or json")
        log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="build_lineage", decision="success", rule_version="lineage:olist@1.0", evidence={"nodes": len(nodes), "edges": len(edges)}), ctx.output_dir.parent / "audit_journal.jsonl")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS, outputs=outputs, message=f"Lineage stored in {backend}")
    except Exception as exc:
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, outputs=outputs, message=str(exc))
