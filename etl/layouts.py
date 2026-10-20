"""Deterministic physical builders; Llama 3 selects a name, never executable SQL."""
from contracts.artifacts import TransformationReceipt


def describe(con, table, keys):
    return {"rows": con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], "grain": "physical_storage", "primary_key": keys, "columns": [{"name": row[1], "type": row[2]} for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()]}


def apply_layout(con, schema_type, keys, receipts):
    """Return actual storage tables, column mappings and physical receipts."""
    columns = {table: [r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()] for table in keys}
    extra = []
    if schema_type == "constellation":
        locations = {table: ["main." + table] for table in keys}
        physical = {"main." + table: describe(con, "main." + table, key) for table, key in keys.items()}
        mappings = {table: {col: [location + "." + col for location in locations[table]] for col in cols} for table, cols in columns.items()}
    elif schema_type == "star":
        con.execute("CREATE SCHEMA items_mart")
        con.execute("CREATE SCHEMA payments_mart")
        locations = {
            "dim_customer": ["items_mart.dim_customer", "payments_mart.dim_customer"],
            "dim_date": ["items_mart.dim_date", "payments_mart.dim_date"],
            "dim_product": ["items_mart.dim_product"], "dim_seller": ["items_mart.dim_seller"],
            "fact_order_items": ["items_mart.fact_order_items"], "fact_payments": ["payments_mart.fact_payments"],
        }
        physical = {}
        by_table = {r["output_table"]: r for r in receipts}
        for table, targets in locations.items():
            for target in targets:
                con.execute(f"CREATE TABLE {target} AS SELECT * FROM {table}")
                con.execute(f"ALTER TABLE {target} ADD PRIMARY KEY ({', '.join(keys[table])})")
                physical[target] = describe(con, target, keys[table])
                original = by_table[table]
                extra.append(TransformationReceipt(**{**original, "output_table": target, "filters": ["physical_layout=independent_star_mart"]}).model_dump())
        for table, targets in locations.items():
            con.execute(f"DROP TABLE {table}")
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM {targets[0]}")
        mappings = {table: {col: [location + "." + col for location in locations[table]] for col in cols} for table, cols in columns.items()}
    elif schema_type == "snowflake":
        con.execute("CREATE TABLE dim_state AS SELECT row_number() OVER (ORDER BY state_code) AS state_key, state_code FROM (SELECT customer_state AS state_code FROM dim_customer UNION SELECT seller_state AS state_code FROM dim_seller) WHERE state_code IS NOT NULL")
        con.execute("ALTER TABLE dim_state ADD PRIMARY KEY (state_key)")
        con.execute("CREATE TABLE dim_product_category AS SELECT row_number() OVER (ORDER BY product_category_name) AS category_key, product_category_name FROM (SELECT DISTINCT product_category_name FROM dim_product WHERE product_category_name IS NOT NULL)")
        con.execute("ALTER TABLE dim_product_category ADD PRIMARY KEY (category_key)")
        con.execute("CREATE TABLE customer_base AS SELECT d.* EXCLUDE(customer_state), s.state_key FROM dim_customer d LEFT JOIN dim_state s ON d.customer_state=s.state_code")
        con.execute("CREATE TABLE seller_base AS SELECT d.* EXCLUDE(seller_state), s.state_key FROM dim_seller d LEFT JOIN dim_state s ON d.seller_state=s.state_code")
        con.execute("CREATE TABLE product_base AS SELECT d.* EXCLUDE(product_category_name), c.category_key FROM dim_product d LEFT JOIN dim_product_category c USING(product_category_name)")
        for base, key in [("customer_base", "customer_id"), ("seller_base", "seller_id"), ("product_base", "product_id")]:
            con.execute(f"ALTER TABLE {base} ADD PRIMARY KEY ({key})")
        for table in ["dim_customer", "dim_seller", "dim_product"]:
            con.execute(f"DROP TABLE {table}")
        con.execute("CREATE VIEW dim_customer AS SELECT b.* EXCLUDE(state_key), s.state_code AS customer_state FROM customer_base b LEFT JOIN dim_state s USING(state_key)")
        con.execute("CREATE VIEW dim_seller AS SELECT b.* EXCLUDE(state_key), s.state_code AS seller_state FROM seller_base b LEFT JOIN dim_state s USING(state_key)")
        con.execute("CREATE VIEW dim_product AS SELECT b.* EXCLUDE(category_key), c.product_category_name FROM product_base b LEFT JOIN dim_product_category c USING(category_key)")
        physical_keys = {"main.fact_order_items": keys["fact_order_items"], "main.fact_payments": keys["fact_payments"], "main.dim_date": keys["dim_date"], "main.customer_base": ["customer_id"], "main.seller_base": ["seller_id"], "main.product_base": ["product_id"], "main.dim_state": ["state_key"], "main.dim_product_category": ["category_key"]}
        physical = {table: describe(con, table, key) for table, key in physical_keys.items()}
        base_names = {"dim_customer": "customer_base", "dim_seller": "seller_base", "dim_product": "product_base"}
        mappings = {}
        for table, cols in columns.items():
            mappings[table] = {}
            for col in cols:
                location = "main." + base_names.get(table, table) + "." + col
                if table in {"dim_customer", "dim_seller"} and col in {"customer_state", "seller_state"}:
                    location = "main.dim_state.state_code"
                elif table == "dim_product" and col == "product_category_name":
                    location = "main.dim_product_category.product_category_name"
                mappings[table][col] = [location]
        sources = {"main.customer_base": ["customers"], "main.seller_base": ["sellers"], "main.product_base": ["products"], "main.dim_state": ["customers", "sellers"], "main.dim_product_category": ["products"]}
        for table, source in sources.items():
            before = sum(next(r["rows_before"] for r in receipts if r["source_tables"] == [name]) for name in source)
            extra.append(TransformationReceipt(output_table=table, source_tables=source, rows_before=before, rows_after=physical[table]["rows"], grain="normalized_dimension", filters=["physical_layout=snowflake"]).model_dump())
    else:
        raise ValueError("Unsupported schema type")
    return physical, mappings, extra
