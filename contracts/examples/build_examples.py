"""Builds every example file from the contract classes, so they are always valid.

    python -m contracts.examples.build_examples

Writes:
  contracts/examples/run_001/<step>/<file>.json   one JSON output of every step
  contracts/examples/static/...                   catalog, glossary, playbook (YAML)
  contracts/examples/audit_events.json            what each agent logs

Scenario: Sarra uploads the Olist tables and asks
  "Revenue by state in August 2018 compared with July 2018".
Counts and revenues marked (real) were computed on the FULL Olist dataset.
Everything else (scores, SHAP values, confidences...) is illustrative.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from contracts.audit import AuditEvent, IntegrityReport
from contracts.analysis import AnalysisResult, Insight, ValidationCheck
from contracts.common import Period, SemanticType, save
from contracts.comparisons import (CheckKind, CheckStatus, ComparisonCheck,
                                   ComparisonReport, ProposedFix)
from contracts.dashboard import ChartSpec, ChartType, DashboardSpec
from contracts.intake import ColumnType, ColumnTypesReport, DatasetMatch, SimilarityReport, Upload
from contracts.pipeline import STEPS
from contracts.privacy import PiiAction, PiiColumn, PiiKind, PiiReport
from contracts.quality import (AnomalyReport, CleaningAction, CleaningReport, CleaningRule,
                               ColumnProfile, Playbook, ProfileReport, RuleApplication,
                               TableProfile)
from contracts.semantic import (AnalysisRequest, Dimension, Glossary, GlossaryTerm,
                                KpiCatalog, KpiDefinition)
from contracts.warehouse import (LineageEdge, LineageGraph, LineageNode, NodeKind, TableKind,
                                 TransformationReceipt, TransformationReceipts,
                                 WarehouseManifest, WarehouseTable)
from contracts.xai import (AnomalyExplanation, DriftReport, ExplanationReport,
                           FeatureContribution, InputDriftCheck, MetricDriftCheck)

HERE = Path(__file__).parent
RUN = HERE / "run_001"
STATIC = HERE / "static"
T0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)

TABLES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}
PARQUET = {t: f"{t}.parquet" for t in TABLES}

AUGUST = Period(start="2018-08-01", end="2018-08-31")
JULY = Period(start="2018-07-01", end="2018-07-31")


def out(step: str, key: str, obj) -> None:
    save(obj, RUN / step / STEPS[step].outputs[key])


def dump_yaml(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(obj.model_dump(mode="json"), sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")


# ---- static files (versioned in the repo) ---------------------------------------
CATALOG = KpiCatalog(
    version="1.0",
    kpis=[
        KpiDefinition(
            name="Revenue", version="2.0",
            description="Money paid by customers for delivered orders.",
            expression="SUM(payment_value)", table="fact_payments", grain="payment",
            date_column="order_purchase_date", unit="BRL",
            filters=["order_status = 'delivered'"],
            allowed_dimensions=["customer_state", "payment_type", "order_month"]),
        KpiDefinition(
            name="Orders", version="1.0",
            description="Number of distinct delivered orders.",
            expression="COUNT(DISTINCT order_id)", table="fact_order_items", grain="order_item",
            date_column="order_purchase_date", unit="orders",
            filters=["order_status = 'delivered'"],
            allowed_dimensions=["customer_state", "product_category", "seller_state", "order_month"]),
    ],
    dimensions=[
        Dimension(name="customer_state", table="dim_customer", column="customer_state",
                  description="Brazilian state of the customer (2 letters)."),
        Dimension(name="product_category", table="dim_product", column="product_category_name_english",
                  description="Product category in English."),
        Dimension(name="seller_state", table="dim_seller", column="seller_state",
                  description="Brazilian state of the seller."),
        Dimension(name="payment_type", table="fact_payments", column="payment_type",
                  description="credit_card, boleto, voucher, debit_card."),
        Dimension(name="order_month", table="dim_date", column="year_month",
                  description="Month of purchase, 'YYYY-MM'."),
    ],
)

GLOSSARY = Glossary(version="1.0", terms=[
    GlossaryTerm(term="Revenue", kind="metric",
                 synonyms=["sales", "turnover", "chiffre d'affaires", "CA", "ventes"],
                 definition="Money paid by customers for delivered orders."),
    GlossaryTerm(term="Orders", kind="metric",
                 synonyms=["number of orders", "commandes", "nombre de commandes"],
                 definition="Distinct delivered orders."),
    GlossaryTerm(term="customer_state", kind="dimension",
                 synonyms=["state", "region", "région", "état"],
                 definition="State where the customer lives."),
    GlossaryTerm(term="last month", kind="time",
                 synonyms=["previous month", "mois dernier"],
                 definition="The calendar month before the current one."),
])

PLAYBOOK = Playbook(
    name="olist", version="1.3", source="manual", approved_by="Ikbel", approved_at=T0,
    rules=[
        CleaningRule(rule_id="R1_drop_duplicate_payments", table="order_payments",
                     action=CleaningAction.DROP_DUPLICATES,
                     description="Delete exact duplicate payment rows (the first one is kept)."),
        CleaningRule(rule_id="R2_cast_purchase_ts", table="orders", column="order_purchase_timestamp",
                     action=CleaningAction.CAST, params={"dtype": "datetime64[ns]"},
                     description="Read the purchase timestamp as a date-time."),
        CleaningRule(rule_id="R3_normalize_city", table="customers", column="customer_city",
                     action=CleaningAction.NORMALIZE_TEXT, params={"case": "lower"},
                     description="Remove surrounding spaces from the city and write it in lower case."),
        CleaningRule(rule_id="R4_fill_median_weight", table="products", column="product_weight_g",
                     action=CleaningAction.FILL_MEDIAN,
                     description="Replace a missing product weight with the median weight."),
    ],
)


def build() -> None:
    dump_yaml(CATALOG, STATIC / "kpi" / "catalog.yaml")
    dump_yaml(GLOSSARY, STATIC / "semantic" / "glossary.yaml")
    dump_yaml(PLAYBOOK, STATIC / "cleaning" / "playbooks" / f"{PLAYBOOK.ref}.yaml")

    # ---- upload (app) ---------------------------------------------------------
    question = "Revenue by state in August 2018 compared with July 2018"
    out("upload", "upload", Upload(question=question, tables=TABLES,
                                   uploaded_by="sarra", uploaded_at=T0))

    # ---- 0. similarity (Malek) ---------------------------------------------------
    olist = DatasetMatch(name="olist", score=0.94, playbook="olist@1.3")
    out("similarity", "report", SimilarityReport(
        method="column-name embeddings + cosine", threshold=0.80,
        matches=[olist, DatasetMatch(name="generic_ecommerce", score=0.61)],
        best_match=olist))

    # ---- 1a. column types (Malek) -------------------------------------------------
    out("column_types", "report", ColumnTypesReport(model="rules+logreg@1.0", columns=[
        ColumnType(table="orders", column="order_id", semantic_type=SemanticType.ID, confidence=0.99),
        ColumnType(table="orders", column="order_purchase_timestamp",
                   semantic_type=SemanticType.DATETIME, confidence=0.99),
        ColumnType(table="order_payments", column="payment_value",
                   semantic_type=SemanticType.AMOUNT, confidence=0.97),
        ColumnType(table="customers", column="customer_unique_id", semantic_type=SemanticType.ID,
                   confidence=0.95, pii_candidate=True),
        ColumnType(table="customers", column="customer_zip_code_prefix",
                   semantic_type=SemanticType.ZIP_CODE, confidence=0.93, pii_candidate=True),
        ColumnType(table="customers", column="customer_state", semantic_type=SemanticType.STATE,
                   confidence=0.98),
    ]))

    # ---- 1b. PII (Ikbel) -------------------------------------------------------------
    out("pii", "report", PiiReport(policy_version="pii-policy@1.0", tables=PARQUET, columns=[
        PiiColumn(table="customers", column="customer_unique_id", pii_kind=PiiKind.PERSON_ID,
                  action=PiiAction.PSEUDONYMIZED, method="sha256 + secret salt",
                  rows_affected=99441),                                              # real
        PiiColumn(table="customers", column="customer_zip_code_prefix", pii_kind=PiiKind.ZIP_CODE,
                  action=PiiAction.GENERALIZED, method="keep first 3 digits",
                  rows_affected=99441),
    ]))

    # ---- 2. profiling + anomalies (Ahmed) --------------------------------------------
    out("profiling", "profile", ProfileReport(tables=[
        TableProfile(table="orders", rows=99441, duplicate_rows=0, columns=[             # real
            ColumnProfile(name="order_approved_at", dtype="object",
                          semantic_type=SemanticType.DATETIME, missing=160,
                          missing_pct=0.0016, distinct=90733),
            ColumnProfile(name="order_delivered_customer_date", dtype="object",
                          semantic_type=SemanticType.DATETIME, missing=2965,
                          missing_pct=0.0298, distinct=95664),
        ]),
        TableProfile(table="order_payments", rows=103886, duplicate_rows=0, columns=[     # real
            ColumnProfile(name="payment_value", dtype="float64", semantic_type=SemanticType.AMOUNT,
                          missing=0, missing_pct=0.0, distinct=29077, min=0.0, max=13664.08),
        ]),
    ]))
    out("profiling", "anomalies", AnomalyReport(
        table="order_payments", row_key="order_id", model="IsolationForest",
        model_version="iforest@1.0",
        params={"n_estimators": 100, "contamination": 0.01, "random_state": 42},
        features=["payment_value", "payment_installments", "payment_sequential"],
        n_rows=103886, n_anomalies=1039))

    # ---- 2a/2b. cleaning (Ikbel) -------------------------------------------------------
    out("cleaning", "report", CleaningReport(
        playbook=PLAYBOOK.ref, tables=PARQUET,
        applied=[RuleApplication(rule_id="R2_cast_purchase_ts", table="orders",
                                 column="order_purchase_timestamp", rows_affected=99441),
                 RuleApplication(rule_id="R4_fill_median_weight", table="products",
                                 column="product_weight_g", rows_affected=2)],
        rows_before={"orders": 99441, "order_payments": 103886, "products": 32951},
        rows_after={"orders": 99441, "order_payments": 103886, "products": 32951}))

    # ---- 3. ETL (Ahmed) -----------------------------------------------------------------
    fact_cols = ["order_id", "payment_sequential", "payment_type", "payment_installments",
                 "payment_value", "customer_id", "order_purchase_date", "order_status"]
    out("etl", "manifest", WarehouseManifest(tables=[
        WarehouseTable(name="fact_payments", kind=TableKind.FACT, grain="payment",
                       primary_key=["order_id", "payment_sequential"], row_count=100756,   # real
                       columns=fact_cols, date_column="order_purchase_date",
                       date_min="2016-09-15", date_max="2018-08-29"),                       # real
        WarehouseTable(name="fact_order_items", kind=TableKind.FACT, grain="order_item",
                       primary_key=["order_id", "order_item_id"], row_count=110197,         # real
                       columns=["order_id", "order_item_id", "product_id", "seller_id", "price",
                                "freight_value", "customer_id", "order_purchase_date", "order_status"],
                       date_column="order_purchase_date",
                       date_min="2016-09-15", date_max="2018-08-29"),
        WarehouseTable(name="dim_customer", kind=TableKind.DIMENSION, grain="customer",
                       primary_key=["customer_id"], row_count=99441,
                       columns=["customer_id", "customer_unique_id", "customer_city", "customer_state"]),
        WarehouseTable(name="dim_product", kind=TableKind.DIMENSION, grain="product",
                       primary_key=["product_id"], row_count=32951,
                       columns=["product_id", "product_category_name_english", "product_weight_g"]),
        WarehouseTable(name="dim_seller", kind=TableKind.DIMENSION, grain="seller",
                       primary_key=["seller_id"], row_count=3095,
                       columns=["seller_id", "seller_city", "seller_state"]),
        WarehouseTable(name="dim_date", kind=TableKind.DIMENSION, grain="day",
                       primary_key=["date"], row_count=774,
                       columns=["date", "year", "month", "year_month", "weekday"]),
    ]))
    out("etl", "receipts", TransformationReceipts(receipts=[
        TransformationReceipt(
            output_table="fact_payments", source_tables=["order_payments", "orders"],
            join_keys=["order_id"], rows_before=103886, rows_after=100756, grain="payment",  # real
            filters=["order_status == 'delivered'"],
            column_sources={"payment_value": "order_payments.payment_value",
                            "order_purchase_date": "orders.order_purchase_timestamp",
                            "order_status": "orders.order_status"}),
        TransformationReceipt(
            output_table="fact_order_items", source_tables=["order_items", "orders"],
            join_keys=["order_id"], rows_before=112650, rows_after=110197, grain="order_item",  # real
            filters=["order_status == 'delivered'"],
            column_sources={"price": "order_items.price",
                            "order_purchase_date": "orders.order_purchase_timestamp"}),
    ]))

    # ---- lineage (Ahmed) ------------------------------------------------------------------
    out("lineage", "graph", LineageGraph(
        nodes=[
            LineageNode(id="raw:order_payments.payment_value", kind=NodeKind.RAW_COLUMN,
                        label="olist_order_payments_dataset.csv / payment_value"),
            LineageNode(id="raw:orders.order_status", kind=NodeKind.RAW_COLUMN,
                        label="olist_orders_dataset.csv / order_status"),
            LineageNode(id="tr:build_fact_payments", kind=NodeKind.TRANSFORMATION,
                        label="join order_payments + orders on order_id, keep delivered"),
            LineageNode(id="table:fact_payments", kind=NodeKind.TABLE, label="fact_payments"),
            LineageNode(id="kpi:Revenue@2.0", kind=NodeKind.KPI, label="Revenue = SUM(payment_value)"),
        ],
        edges=[
            LineageEdge(source="raw:order_payments.payment_value", target="tr:build_fact_payments",
                        relation="read"),
            LineageEdge(source="raw:orders.order_status", target="tr:build_fact_payments",
                        relation="filtered order_status == 'delivered'"),
            LineageEdge(source="tr:build_fact_payments", target="table:fact_payments",
                        relation="wrote"),
            LineageEdge(source="table:fact_payments", target="kpi:Revenue@2.0",
                        relation="aggregated SUM(payment_value)"),
        ]))

    # ---- 4. request (Malek) -------------------------------------------------------------------
    request = AnalysisRequest(
        question=question, metric="Revenue", dimensions=["customer_state"],
        period=AUGUST, compare_to=JULY, confidence=0.91,
        matched_terms={"Revenue": "Revenue", "state": "customer_state"})
    out("request", "request", request)

    # ---- 5. analysis (Rabeb) ------------------------------------------------------------------
    result = AnalysisResult(
        request=request, kpi="Revenue@2.0",
        sql=("SELECT c.customer_state, CASE WHEN f.order_purchase_date >= '2018-08-01' "
             "THEN 'current' ELSE 'previous' END AS period, SUM(f.payment_value) AS value "
             "FROM fact_payments f JOIN dim_customer c USING (customer_id) "
             "WHERE f.order_status = 'delivered' "
             "AND f.order_purchase_date BETWEEN '2018-07-01' AND '2018-08-31' "
             "GROUP BY 1, 2"),
        rows=54, unit="BRL",
        value_current=985414.28, value_previous=1027903.86, change_pct=-0.0413,            # real
        validations=[
            ValidationCheck(name="join_multiplicity", passed=True,
                            detail="fact_payments has 100756 rows for 100756 delivered payments: "
                                   "the join did not duplicate rows."),
            ValidationCheck(name="grain_matches_kpi", passed=True,
                            detail="Revenue@2.0 expects grain 'payment'; fact_payments grain is 'payment'."),
        ],
        insights=[Insight(text="São Paulo (SP) makes 45% of August revenue.",
                          evidence={"SP": 443770.05, "total": 985414.28})])                  # real
    out("analysis", "result", result)

    # ---- 6. comparisons (Tasnim) ----------------------------------------------------------------
    out("comparisons", "report", ComparisonReport(
        has_comparison=True,
        checks=[
            ComparisonCheck(
                kind=CheckKind.COVERAGE, status=CheckStatus.BLOCKING,
                message=("August has data only up to the 29th (29 of 31 days), July is complete. "
                         "The full-month comparison shows a 4.1% drop that is caused by missing days."),
                evidence={"current_last_day": "2018-08-29", "current_days": 29,
                          "previous_days": 31, "warehouse_date_max": "2018-08-29"}),
            ComparisonCheck(kind=CheckKind.UNIT, status=CheckStatus.OK,
                            message="Both periods are in BRL."),
            ComparisonCheck(kind=CheckKind.GRAIN, status=CheckStatus.OK,
                            message="Both periods use fact_payments (one row = one payment)."),
            ComparisonCheck(kind=CheckKind.POPULATION, status=CheckStatus.OK,
                            message="Same filter (delivered orders) on both periods."),
        ],
        proposed_fix=ProposedFix(
            description="Compare 1-29 August 2018 with 1-29 July 2018.",
            period=Period(start="2018-08-01", end="2018-08-29"),
            compare_to=Period(start="2018-07-01", end="2018-07-29"),
            value_current=985414.28, value_previous=930969.67, change_pct=0.0585)))         # real

    # ---- 6. dashboard (Samar) -------------------------------------------------------------------
    out("dashboard", "spec", DashboardSpec(
        title="Revenue by state: August vs July 2018", question=question, kpi="Revenue@2.0",
        charts=[
            ChartSpec(chart_id="c1", chart_type=ChartType.KPI_CARD, title="Revenue, 1-29 August",
                      data_file="analysis/result.parquet", y="value",
                      reason="One headline number with its change."),
            ChartSpec(chart_id="c2", chart_type=ChartType.BAR, title="Revenue by state",
                      data_file="analysis/result.parquet", x="customer_state", y="value",
                      color="period", reason="27 categories compared across 2 periods."),
        ],
        warnings=["August is incomplete (29 of 31 days). Showing 1-29 August vs 1-29 July."]))

    # ---- 7. auditor (Tasnim) --------------------------------------------------------------------
    contribs = [FeatureContribution(feature="payment_value", value=13664.08, shap_value=4.1),
                FeatureContribution(feature="payment_installments", value=1, shap_value=0.3),
                FeatureContribution(feature="payment_sequential", value=1, shap_value=-0.2)]
    base = -11.6
    out("auditor", "explanations", ExplanationReport(
        table="order_payments", model_version="iforest@1.0", explainer="shap.TreeExplainer",
        explanations=[AnomalyExplanation(
            row_key="03caa2c082116e1d31e67e9ae3700499", is_anomaly=True, anomaly_score=0.78,
            base_value=base, model_output=round(base + sum(c.shap_value for c in contribs), 6),
            contributions=contribs,
            narrative=("Flagged as anomalous because Payment Value (13,664.08, far above the typical "
                       "100.00) accounted for 93% of the push toward anomaly. The model isolated "
                       "this payment in 7.4 splits, versus 11.6 for a typical row."))]))
    out("auditor", "drift", DriftReport(
        reference_runs=["run_2018_05", "run_2018_06", "run_2018_07"], current_run="run_001",
        status="stable",
        input_checks=[InputDriftCheck(agent="profiling", name="payment_value", psi=0.04,
                                      ks_pvalue=0.21, flagged=False)],
        metric_checks=[MetricDriftCheck(agent="profiling", name="anomaly_rate", value=0.0101,
                                        center=0.0100, lower=0.0091, upper=0.0109,
                                        out_of_control=False)],
        narrative="Inputs and outputs are within the reference limits. "
                  "This is a diagnosis, not a proof: a human decides."))

    out("auditor", "integrity", IntegrityReport(
        ok=True, entries_checked=5, problem="All entries verified: the chain is intact."))

    # ---- what agents write in the journal ----------------------------------------------------
    events = [
        AuditEvent(run_id="run_001", agent="pii", step="pseudonymize", timestamp=T0,
                   decision="pseudonymized customers.customer_unique_id",
                   inputs=["upload/tables/olist_customers_dataset.csv"],
                   outputs=["pii/tables/customers.parquet"], rule_version="pii-policy@1.0",
                   evidence={"rows_affected": 99441, "method": "sha256 + secret salt"}),
        AuditEvent(run_id="run_001", agent="cleaning", step="R4_fill_median_weight", timestamp=T0,
                   decision="filled 2 missing product_weight_g with the median 700",
                   inputs=["pii/tables/products.parquet"], outputs=["cleaning/tables/products.parquet"],
                   rule_version="playbook:olist@1.3",
                   evidence={"rows_affected": 2, "median": 700}),
        AuditEvent(run_id="run_001", agent="etl", step="build_fact_payments", timestamp=T0,
                   decision="PASSED", inputs=["order_payments", "orders"], outputs=["fact_payments"],
                   evidence={"rows_before": 103886, "rows_after": 100756}),
        AuditEvent(run_id="run_001", agent="analysis", step="join_multiplicity", timestamp=T0,
                   decision="PASSED", inputs=["etl/receipts.json"], rule_version="kpi:Revenue@2.0",
                   evidence={"expected_rows": 100756, "actual_rows": 100756}),
        AuditEvent(run_id="run_001", agent="comparisons", step="coverage_check", timestamp=T0,
                   decision="BLOCKING: fix proposed (1-29 Aug vs 1-29 Jul)",
                   inputs=["request/analysis_request.json", "etl/warehouse_manifest.json"],
                   evidence={"current_days": 29, "previous_days": 31}),
    ]
    (HERE / "audit_events.json").write_text(
        TypeAdapter(list[AuditEvent]).dump_json(events, indent=2).decode(), encoding="utf-8")


if __name__ == "__main__":
    build()
    files = sorted(p.relative_to(HERE) for p in HERE.rglob("*") if p.is_file() and p.suffix in {".json", ".yaml"})
    print(f"{len(files)} example files written:")
    for f in files:
        print("  ", f)
