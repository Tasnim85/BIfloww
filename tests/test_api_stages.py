"""The pipeline view (what every agent wrote) and Malek's parser over HTTP. No Olist, no LLM.
python -m pytest tests/test_api_stages.py -v
"""
import json

import pytest
from fastapi.testclient import TestClient

import contracts.llm as llm
from api.main import create_app
from api.stages import kpi_path
from auditor.dev import clinics
from contracts.pipeline import REPO_ROOT, STEPS, output_path
from contracts.warehouse import LineageEdge, LineageGraph, LineageNode

RUN = "clinic_001"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("stages")
    runs = root / "runs"
    clinics.write_run(root, RUN, clinics.visits())
    return TestClient(create_app(runs_root=runs, repo_root=root)), runs, root


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    def down(*a, **k):
        raise llm.LLMUnavailable("LLM disabled in this test")
    monkeypatch.setattr(llm, "_post", down)


def test_every_step_is_listed_with_where_its_files_come_from(world):
    c, runs, root = world
    v = c.get(f"/api/runs/{RUN}/pipeline").json()
    assert [s["step"] for s in v["stages"]] == list(STEPS)
    by = {s["step"]: s for s in v["stages"]}
    assert by["etl"]["available"] and by["request"]["available"]
    assert not by["similarity"]["available"] and v["similarity"] is None      # never invented
    assert by["etl"]["scope"] == "dataset" and by["analysis"]["scope"] == "question"
    assert v["etl"]["manifest"]["tables"] and v["request"]["metric"] == "Consultation revenue"
    assert str(root) not in json.dumps(v)                                     # no local path leaks


def test_a_new_question_runs_the_analyst_and_reuses_the_data_steps(world):
    c, runs, _ = world
    body = {"base_run": RUN, "metric": "Consultation revenue", "dimensions": ["region"],
            "period": {"start": "2024-03-01", "end": "2024-03-31"},
            "compare_to": {"start": "2024-02-01", "end": "2024-02-29"}, "question": "Revenue by region",
            "confidence": 0.8, "matched_terms": {"region": "region"}}
    r = c.post("/api/comparisons", json=body)
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    v = c.get(f"/api/runs/{rid}/pipeline").json()
    by = {s["step"]: s for s in v["stages"]}
    assert v["base_run"] == RUN and by["etl"]["source_run"] == RUN and by["analysis"]["source_run"] == rid
    assert by["analysis"]["available"], "Rabeb's analyst must run on the new question"
    assert by["auditor"]["source_run"] == RUN                  # SHAP / drift are about the data: base run
    a = v["analysis"]
    assert a["request"]["question"] == "Revenue by region" and a["value_current"] is not None
    assert v["request"]["matched_terms"] == {"region": "region"} and v["request"]["confidence"] == 0.8
    assert {x["name"] for x in a["validations"]} and all(isinstance(x["passed"], bool) for x in a["validations"])
    # its decisions go to the UI journal, never to the real one
    assert not (runs / "audit_journal.db").exists()
    events = c.get(f"/api/runs/{rid}/journal").json()
    assert {"analysis", "comparisons", "dashboard"} <= {e["agent"] for e in events}
    # Samar's dashboard agent chose the charts; they follow the user's decision
    charts = c.get(f"/api/runs/{rid}/charts").json()
    assert charts["charts"][0]["chart_type"] == "kpi_card" and all(ch["reason"] for ch in charts["charts"])
    assert by["dashboard"]["source_run"] == rid
    report = c.get(f"/api/runs/{rid}/comparison").json()
    if report["proposed_fix"]:
        c.post(f"/api/runs/{rid}/comparison/decision", json={"decision": "rejected"})
        after = c.get(f"/api/runs/{rid}/charts").json()
        assert after["comparison_shown"] is True


def test_unknown_or_escaping_run_ids(world):
    c, *_ = world
    assert c.get("/api/runs/nope/pipeline").status_code == 404
    assert c.get("/api/runs/a.b/pipeline").status_code == 422
    assert c.get("/api/runs/..%2Fx/pipeline").status_code in (404, 422)


def test_lineage_path_keeps_only_what_feeds_the_kpi():
    n = lambda i, k="transformation": LineageNode(id=i, kind=k, label=i)          # noqa: E731
    e = lambda s, t: LineageEdge(source=s, target=t, relation="r")                  # noqa: E731
    g = LineageGraph(nodes=[n("raw:a.x", "raw_column"), n("clean:a.x"), n("warehouse:f.x"), n("kpi:K@1.0", "kpi"),
                            n("raw:b.y", "raw_column"), n("warehouse:g.y"), n("kpi:Other@1.0", "kpi")],
                     edges=[e("raw:a.x", "clean:a.x"), e("clean:a.x", "warehouse:f.x"), e("warehouse:f.x", "kpi:K@1.0"),
                            e("raw:b.y", "warehouse:g.y"), e("warehouse:g.y", "kpi:Other@1.0")])
    p = kpi_path(g, "K@1.0")
    assert {x.id for x in p.nodes} == {"raw:a.x", "clean:a.x", "warehouse:f.x", "kpi:K@1.0"}
    assert len(p.edges) == 3 and p.total_nodes == 7
    assert kpi_path(g, "Missing@1.0") is None


def test_parse_proposes_a_request_without_touching_any_journal(tmp_path):
    runs = tmp_path / "runs"
    (runs / "olist_x").mkdir(parents=True)
    c = TestClient(create_app(runs_root=runs, repo_root=REPO_ROOT))          # the repo's glossary + catalog
    r = c.post("/api/parse", json={"question": "Revenue by customer state, August 2018 vs July 2018",
                                   "base_run": "olist_x"}).json()
    assert r["status"] == "success"
    req = r["request"]
    assert req["metric"] == "Revenue" and req["dimensions"] == ["customer_state"]
    assert req["period"] == {"start": "2018-08-01", "end": "2018-08-31"}
    assert req["compare_to"] == {"start": "2018-07-01", "end": "2018-07-31"}
    fr = c.post("/api/parse", json={"question": "Combien de commandes en mai 2018 contre avril 2018 ?",
                                    "base_run": "olist_x"}).json()
    assert fr["request"]["metric"] == "Orders" and fr["request"]["period"]["start"] == "2018-05-01"
    unclear = c.post("/api/parse", json={"question": "bonjour", "base_run": "olist_x"}).json()
    assert unclear["status"] == "needs_review" and unclear["request"] is None
    assert list(runs.glob("*.db")) == [] and [p.name for p in runs.iterdir()] == ["olist_x"]
    assert c.post("/api/parse", json={"question": "Revenue", "base_run": "../etc"}).status_code == 422
    assert c.post("/api/parse", json={"question": "Revenue", "base_run": "nope"}).status_code == 404


def test_side_files_with_local_paths_are_never_read(world):
    c, runs, root = world
    side = output_path(RUN, "etl", "manifest", runs).with_name("warehouse_manifest.bo2.json")
    side.write_text(json.dumps({"path": str(root / "secret")}), encoding="utf-8")
    assert "secret" not in c.get(f"/api/runs/{RUN}/pipeline").text
    side.unlink()


def test_dashboard_total_of_a_distinct_count_is_not_the_sum_of_its_groups(tmp_path):
    """Orders by category: an order with items in 2 categories counts once in the total."""
    import duckdb
    from comparisons.values import kpi_by_dimension
    from contracts.common import Period
    from contracts.semantic import AnalysisRequest, KpiCatalog
    from contracts.warehouse import WarehouseManifest
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE fact_items(order_id VARCHAR, category VARCHAR, d DATE)")
    con.execute("INSERT INTO fact_items VALUES ('o1','toys','2018-05-02'),('o1','books','2018-05-02'),('o2','toys','2018-05-03')")
    con.close()
    catalog = KpiCatalog.model_validate({"version": "test", "kpis": [{"name": "Orders", "version": "1.0", "description": "orders", "expression": "COUNT(DISTINCT order_id)",
        "table": "fact_items", "date_column": "d", "grain": "item", "unit": "orders", "allowed_dimensions": ["category"]}],
        "dimensions": [{"name": "category", "table": "fact_items", "column": "category", "description": "c"}]})
    manifest = WarehouseManifest.model_validate({"database_file": "w.duckdb", "tables": [{"name": "fact_items", "kind": "fact",
        "grain": "item", "primary_key": [], "row_count": 3, "columns": ["order_id", "category", "d"], "date_column": "d"}]})
    req = AnalysisRequest(question="q", metric="Orders", dimensions=["category"], period=Period(start="2018-05-01", end="2018-05-31"))
    b = kpi_by_dimension(db, manifest, catalog, req, req.period, None)
    assert {r.label: r.current for r in b.rows} == {"toys": 2.0, "books": 1.0}
    assert b.total_current == 2.0                        # not 3
