"""Ahmed: independent item/payment facts without many-to-many multiplication."""
import json
import os
import hashlib
from decimal import Decimal
import duckdb
import pandas as pd

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.artifacts import TransformationReceipt
from contracts.audit import AuditEvent, log_event
from .models import WarehouseManifest
from .layouts import apply_layout
from .schema_advisor import recommend

KEYS = {"customers": ["customer_id"], "orders": ["order_id"], "products": ["product_id"], "sellers": ["seller_id"], "order_items": ["order_id", "order_item_id"], "order_payments": ["order_id", "payment_sequential"]}
REQUIRED = {
    "customers": ["customer_id", "customer_unique_id", "customer_state", "customer_zip_code_prefix", "customer_city"],
    "orders": ["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_delivered_customer_date"],
    "products": ["product_id", "product_category_name"],
    "sellers": ["seller_id", "seller_state"],
    "order_items": ["order_id", "order_item_id", "product_id", "seller_id", "price", "freight_value"],
    "order_payments": ["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"],
}


def run(ctx: RunContext) -> AgentResult:
    mode = ctx.params.get("warehouse_mode", "auto")
    if mode == "dimensional":
        from .dimensional import run as run_dimensional
        return run_dimensional(ctx)
    files = {path.stem for path in ctx.inputs.get("tables", ctx.output_dir).glob("*.parquet")}
    if mode == "generic" or (mode == "auto" and files != set(KEYS) and (ctx.params.get("schema_mode", "llm") == "llm" or not set(KEYS).issubset(files))):
        from .generic import run as run_generic
        return run_generic(ctx)
    return run_olist(ctx)


def run_olist(ctx: RunContext) -> AgentResult:
    connection = None
    owns_temporary = False
    published = []
    completed = False
    temporary = ctx.output_dir / "warehouse.building.duckdb"
    try:
        if ctx.agent != "etl" or ctx.inputs["tables"].parent.name != "cleaning":
            raise ValueError("ETL must consume cleaning/tables")
        clean_report = json.loads(ctx.inputs["cleaning_report"].read_text(encoding="utf-8"))
        if clean_report["needs_review"]:
            raise ValueError("Cleaning has pending human review")
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        if any((ctx.output_dir / name).exists() for name in ("warehouse.duckdb", "receipts.json", "warehouse_manifest.json")):
            raise ValueError("Completed warehouse artifacts exist; use a fresh output directory")
        source_paths = [ctx.inputs["cleaning_report"], *[ctx.inputs["tables"] / f"{name}.parquet" for name in KEYS]]
        def fingerprints():
            hashes = {}
            for path in source_paths:
                with path.open("rb") as stream:
                    hashes[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
            return hashes
        source_hashes = fingerprints()
        frames = {name: pd.read_parquet(ctx.inputs["tables"] / f"{name}.parquet") for name in KEYS}
        for name, frame in frames.items():
            missing = set(REQUIRED[name]) - set(frame)
            if missing:
                raise ValueError(f"Missing columns in {name}: {sorted(missing)}")
            keys = KEYS[name]
            if frame[keys].isna().any().any() or frame.duplicated(keys).any():
                raise ValueError(f"Null or duplicate primary key in {name}: {keys}")
        checks = [("orders", "customer_id", "customers"), ("order_items", "order_id", "orders"), ("order_payments", "order_id", "orders"), ("order_items", "product_id", "products"), ("order_items", "seller_id", "sellers")]
        for child, column, parent in checks:
            count = int((~frames[child][column].isin(frames[parent][column])).sum())
            if count:
                raise ValueError(f"Orphan foreign key {child}.{column}: {count} rows")
        for name, columns in {"order_items": ["price", "freight_value"], "order_payments": ["payment_value"]}.items():
            for col in columns:
                values = pd.to_numeric(frames[name][col], errors="coerce")
                if values.isna().any() or (values < 0).any() or (~values.map(lambda x: float('-inf') < x < float('inf'))).any():
                    raise ValueError(f"Invalid financial amount: {name}.{col}")
                if any(Decimal(str(value)) != Decimal(str(value)).quantize(Decimal("0.01")) for value in values):
                    raise ValueError(f"Financial amounts require at most two decimal places: {name}.{col}")
        # Typed warehouse dates are validated here without changing cleaned files.
        orders = frames["orders"]
        for column in orders:
            if "timestamp" in column or "date" in column or column == "order_approved_at":
                original = orders[column]
                parsed = pd.to_datetime(original, errors="coerce", format="mixed")
                if (original.notna() & parsed.isna()).any():
                    raise ValueError(f"Invalid date in orders.{column}; review cleaning")
                orders[column] = parsed
        if orders.order_purchase_timestamp.isna().any():
            raise ValueError("Valid purchase dates required")
        schema_mode = ctx.params.get("schema_mode", "llm")
        recommendation_path = None
        if schema_mode == "llm":
            recommendation = recommend(frames, ctx.params.get("workload", "Olist BI: payments and item sales by time, customer state, product category and seller; shared KPI catalog; prioritize correct grains and simple analytical queries"), ctx.params.get("llm_model"))
            schema_type = recommendation.schema_type
            recommendation_path = ctx.output_dir / "schema_recommendation.json"
            recommendation_path.write_text(recommendation.model_dump_json(indent=2), encoding="utf-8")
            log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="recommend_warehouse_schema", decision=schema_type, rule_version="schema-advisor:llama3@1.0", evidence={"model": ctx.params.get("llm_model") or os.environ.get("OLLAMA_MODEL", "llama3:latest"), "rationale": recommendation.rationale, "validation_basis": "metadata_not_benchmark"}), ctx.output_dir.parent / "audit_journal.jsonl")
        elif schema_mode in {"star", "snowflake", "constellation"}:
            schema_type = schema_mode
        else:
            raise ValueError("schema_mode must be llm, star, snowflake or constellation")
        if temporary.exists():
            raise ValueError("A previous warehouse.building.duckdb exists; use a fresh run directory")
        connection = duckdb.connect(str(temporary))
        owns_temporary = True
        for name, frame in frames.items():
            connection.register("src_" + name, frame)
        connection.execute("CREATE TABLE dim_customer AS SELECT * FROM src_customers")
        connection.execute("CREATE TABLE dim_product AS SELECT * FROM src_products")
        connection.execute("CREATE TABLE dim_seller AS SELECT * FROM src_sellers")
        dates = pd.concat([pd.to_datetime(frames["orders"][col], errors="coerce") for col in frames["orders"] if "timestamp" in col or "date" in col]).dropna()
        if dates.empty or frames["orders"].order_purchase_timestamp.isna().any():
            raise ValueError("Valid purchase dates required")
        calendar = pd.DataFrame({"date": pd.date_range(dates.min().normalize(), dates.max().normalize())})
        calendar["date_key"] = calendar.date.dt.strftime("%Y%m%d").astype(int)
        calendar["year"] = calendar.date.dt.year
        calendar["month"] = calendar.date.dt.month
        calendar["day"] = calendar.date.dt.day
        connection.register("calendar", calendar)
        connection.execute("CREATE TABLE dim_date AS SELECT date_key, CAST(date AS DATE) AS date, year, month, day FROM calendar")
        # Explicit decimals prevent binary floating-point errors in financial sums.
        for name, money in [("order_items", ["price", "freight_value"]), ("order_payments", ["payment_value"])]:
            quoted = {col: '"' + col.replace('"', '""') + '"' for col in frames[name]}
            fields = [f"i.{quoted[col]}" if col not in money else f"CAST(i.{quoted[col]} AS DECIMAL(18,2)) AS {quoted[col]}" for col in frames[name]]
            fact = "fact_order_items" if name == "order_items" else "fact_payments"
            query = "CREATE TABLE " + fact + " AS SELECT " + ", ".join(fields) + ", o.customer_id, o.order_status, o.order_purchase_timestamp, o.order_delivered_customer_date, CAST(strftime(o.order_purchase_timestamp, '%Y%m%d') AS INTEGER) AS purchase_date_key FROM src_" + name + " i JOIN src_orders o ON i.order_id = o.order_id"
            connection.execute(query)
        primary_keys = {"dim_customer": ["customer_id"], "dim_product": ["product_id"], "dim_seller": ["seller_id"], "dim_date": ["date_key"], "fact_order_items": KEYS["order_items"], "fact_payments": KEYS["order_payments"]}
        grains = {"dim_customer": "customer_id (order-specific customer identifier)", "dim_product": "product", "dim_seller": "seller", "dim_date": "calendar_day", "fact_order_items": "order_item", "fact_payments": "order_payment"}
        receipts = []
        manifest = {}
        for table, keys in primary_keys.items():
            connection.execute(f"ALTER TABLE {table} ADD PRIMARY KEY ({', '.join(keys)})")
            rows = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if table.startswith("fact_"):
                source = "order_items" if table == "fact_order_items" else "order_payments"
                if rows != len(frames[source]):
                    raise ValueError(f"Join changed grain for {table}")
                receipt = TransformationReceipt(output_table=table, source_tables=[source, "orders"], join_keys=["order_id"], rows_before=len(frames[source]), rows_after=rows, grain=grains[table], filters=[])
            else:
                source = {"dim_customer": "customers", "dim_product": "products", "dim_seller": "sellers", "dim_date": "orders"}[table]
                receipt = TransformationReceipt(output_table=table, source_tables=[source], join_keys=[], rows_before=len(frames[source]), rows_after=rows, grain=grains[table])
            receipts.append(receipt.model_dump())
            manifest[table] = {"rows": rows, "grain": grains[table], "primary_key": keys, "columns": [{"name": row[1], "type": row[2]} for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()]}
            log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="build_table_and_check_grain", decision="success", rule_version="etl:olist@1.0", evidence=receipt.model_dump()), ctx.output_dir.parent / "audit_journal.jsonl")
        physical, mappings, extra_receipts = apply_layout(connection, schema_type, primary_keys, receipts)
        receipts.extend(extra_receipts)
        log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="build_physical_layout", decision=schema_type, rule_version="etl-layout:olist@1.0", evidence={"physical_tables": list(physical), "physical_receipts": len(extra_receipts)}), ctx.output_dir.parent / "audit_journal.jsonl")
        for table, info in manifest.items():
            if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] != info["rows"]:
                raise ValueError("Physical layout changed the canonical table grain")
            info["physical_sources"] = mappings[table]
            info["kind"] = "view" if schema_type == "star" or (schema_type == "snowflake" and table in {"dim_customer", "dim_product", "dim_seller"}) else "table"
            info["columns"] = [{"name": row[1], "type": row[2]} for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()]
        source_total = sum(Decimal(str(v)).quantize(Decimal('0.01')) for v in frames["order_payments"].payment_value)
        total = connection.execute("SELECT coalesce(sum(payment_value), 0) FROM fact_payments").fetchone()[0]
        if total != source_total:
            raise ValueError("Payment reconciliation failed")
        connection.close()
        connection = None
        warehouse = ctx.output_dir / "warehouse.duckdb"
        receipt_path = ctx.output_dir / "receipts.json"
        receipt_data = json.dumps(receipts, indent=2)
        manifest_path = ctx.output_dir / "warehouse_manifest.json"
        manifest_data = WarehouseManifest(warehouse=str(warehouse), tables=manifest, reconciliation={"payments_source": str(source_total), "payments_warehouse": str(total)}, revenue_catalog_status="owned_by_Rabeb_not_defined_here", schema_type=schema_type, schema_selection="llm" if schema_mode == "llm" else "explicit", schema_recommendation=str(recommendation_path) if recommendation_path else None, physical_tables=physical, cleaning_source=str(ctx.inputs["tables"].parent.resolve()), source_fingerprints=source_hashes).model_dump_json(indent=2)
        if fingerprints() != source_hashes:
            raise ValueError("Cleaned inputs changed during warehouse preparation; retry")
        # Publish the database last; failed publication removes this attempt's files.
        for path, content in [(receipt_path, receipt_data), (manifest_path, manifest_data)]:
            staging = path.with_suffix(".building.json")
            try:
                staging.write_text(content, encoding="utf-8")
                staging.rename(path)
                published.append(path)
            finally:
                staging.unlink(missing_ok=True)
        temporary.rename(warehouse)
        published.append(warehouse)
        completed = True
        outputs = {"warehouse": warehouse, "manifest": manifest_path, "receipts": receipt_path}
        if recommendation_path:
            outputs["recommendation"] = recommendation_path
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS, outputs=outputs, message=f"Built {schema_type} layout")
    except Exception as exc:
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, message=str(exc))
    finally:
        if not completed:
            for path in published:
                path.unlink(missing_ok=True)
        if connection is not None:
            connection.close()
        if owns_temporary and temporary.exists():
            temporary.unlink()
