"""Ahmed: file/column lineage from ETL receipts without reopening raw data."""
import json
import hashlib

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.warehouse import TransformationReceipt
from contracts.audit import AuditEvent, log_event
from .models import LineageReport, WarehouseManifest
from bo2.artifact_io import read_artifact_text


def _run(ctx: RunContext) -> AgentResult:
    outputs = {}
    try:
        if ctx.agent != "lineage":
            raise ValueError("Expected agent='lineage'")
        tracked = {key:path for key,path in ctx.inputs.items() if key in {"manifest","receipts","privacy_report","cleaning_report","warehouse","catalog"}}
        def fingerprints():
            hashes={}
            for key,path in tracked.items():
                with path.open("rb") as stream:
                    hashes[key]=hashlib.file_digest(stream,"sha256").hexdigest()
            return hashes
        source_hashes=fingerprints()
        receipts = [TransformationReceipt.model_validate(item) for item in json.loads(read_artifact_text(ctx.inputs["receipts"]))]
        manifest = WarehouseManifest.model_validate_json(read_artifact_text(ctx.inputs["manifest"])).model_dump()
        canonical = set(manifest["tables"])
        written = [r.output_table for r in receipts if r.output_table in canonical]
        if set(written) != canonical or len(written)!=len(set(written)):
            raise ValueError("Missing or duplicate canonical transformation receipt")
        privacy = {}
        if "privacy_report" in ctx.inputs:
            report=json.loads(read_artifact_text(ctx.inputs["privacy_report"]))
            privacy={f"{item['table']}.{item['column']}":item['action'] for item in report.get("classification",[])}
        cleaned={}
        if "cleaning_report" in ctx.inputs:
            report=json.loads(read_artifact_text(ctx.inputs["cleaning_report"]))
            for item in report.get("changes",[]):
                if "column" in item and "action" in item:
                    cleaned.setdefault(f"{item['table']}.{item['column']}",[]).append(item["action"])
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
            if manifest.get("modeling_version") == 2:
                table = receipt.output_table
                for column in manifest["tables"][table]["columns"]:
                    col = column["name"]
                    target = f"warehouse:{table}.{col}"
                    storage = manifest["tables"][table]["physical_sources"].get(col, [])
                    physical_targets = [f"physical:{location}" for location in storage] or [target]
                    sources = manifest["column_sources"].get(table, {}).get(col, [])
                    for source in sources:
                        connect(f"raw:{source}", f"pii:{source}", "privacy:"+privacy[source] if source in privacy else "privacy_policy")
                        connect(f"pii:{source}", f"clean:{source}", "cleaning:"+",".join(cleaned[source]) if source in cleaned else "approved_cleaning")
                        for physical_target in physical_targets:
                            operation="dimensional_etl"
                            if any(binding["warehouse_column"]==col and binding["source_column"]!=col for binding in manifest.get("measure_bindings",{}).get(table,[])):
                                operation="cast_numeric_measure"
                            connect(f"clean:{source}", physical_target, operation)
                    if not sources:
                        operation = f"transformation:{table}.{col}"
                        for source_table in receipt.source_tables:
                            connect(f"raw:{source_table}", f"pii:{source_table}", "privacy_policy")
                            connect(f"pii:{source_table}", f"clean:{source_table}", "approved_cleaning")
                            connect(f"clean:{source_table}", operation, "row_identity_or_derived_column")
                        for physical_target in physical_targets:
                            connect(operation, physical_target, "generated_column")
                    for physical_target in physical_targets:
                        if physical_target != target:
                            connect(physical_target, target, "canonical_table_or_view")
                for link in manifest.get("dimensional_links", []):
                    if link["fact"] == table:
                        connect(f"warehouse:{link['dimension']}.{link['target_key']}", f"warehouse:{table}.{link['column']}", "verified_dimension_lookup")
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
        bindings = ctx.params.get("metric_sources", {} if manifest.get("source_tables") else {"Revenue_demo": {"table": "fact_payments", "column": "payment_value"}})
        for metric, binding in bindings.items():
            sources = binding.get("sources", [binding])
            if not isinstance(sources,list) or not sources:
                raise ValueError("Metric binding needs source columns")
            for source in sources:
                table, column = source["table"], source["column"]
                if table not in manifest["tables"] or column not in {x["name"] for x in manifest["tables"][table]["columns"]}:
                    raise ValueError("Invalid metric source binding")
                connect(f"warehouse:{table}.{column}", f"kpi:{metric}", "catalog_binding" if "metric_sources" in ctx.params else "demo_binding_pending_Rabeb_catalog")
        # Deduplicate edges because a calendar is derived from several dates.
        edges = list({(e["source"], e["target"], e["operation"]): e for e in edges}.values())
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.output_dir / "lineage.json"
        identity={"inputs":source_hashes,"nodes":sorted(nodes),"edges":sorted((e["source"],e["target"],e["operation"]) for e in edges)}
        scope=ctx.params.get("graph_run_id") or ctx.run_id+"__"+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
        if fingerprints()!=source_hashes:
            raise ValueError("ETL inputs changed during lineage construction")
        graph = LineageReport(nodes=list(nodes.values()), edges=edges, graph_run_id=scope,
            etl_source=str(ctx.inputs["manifest"].parent.resolve()),source_fingerprints=source_hashes,
            integration_status="kpi_bindings_provided" if bindings else "bo2_only")
        # Never silently replace a different lineage snapshot in the same directory.
        if path.exists() and json.loads(read_artifact_text(path))!=graph.model_dump():
            raise ValueError("Different lineage snapshot already exists; choose a new output directory")
        path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
        outputs["lineage"] = path
        backend = ctx.params.get("backend", "neo4j")
        if backend == "neo4j":
            from .neo4j_store import import_graph
            report = import_graph(graph, scope)
            imported = ctx.output_dir / "neo4j_import.json"
            imported.write_text(json.dumps(report, indent=2), encoding="utf-8")
            outputs["neo4j_import"] = imported
        elif backend != "json":
            raise ValueError("Lineage backend must be neo4j or json")
        log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="build_lineage", decision="success", rule_version="lineage@2.0", evidence={"nodes": len(nodes), "edges": len(edges)}), ctx.journal)
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS, outputs=outputs, message=f"Lineage stored in {backend}")
    except Exception as exc:
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, outputs=outputs, message=str(exc))


def run(ctx: RunContext) -> AgentResult:
    from bo2.contract_adapter import execute
    return execute(ctx, _run)
