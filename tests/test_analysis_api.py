"""Rabeb's HTTP API, on the mini warehouse, in a temporary folder (no Olist, no LLM).
python -m pytest tests/test_analysis_api.py -v
"""
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import contracts.llm as llm  # noqa: E402
from analysis.api.main import create_app  # noqa: E402
from analysis.dev_warehouse import build  # noqa: E402
from contracts.common import CONTRACTS_VERSION  # noqa: E402
from contracts.pipeline import REPO_ROOT  # noqa: E402

AUGUST = {"start": "2018-08-01", "end": "2018-08-31"}
JULY = {"start": "2018-07-01", "end": "2018-07-31"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    def down(*a, **k):
        raise llm.LLMUnavailable("LLM disabled in this test")
    monkeypatch.setattr(llm, "_post", down)
    runs = tmp_path / "runs"
    build("dev_001", runs)
    journal = tmp_path / "journal.db"
    return TestClient(create_app(runs_root=runs, repo_root=REPO_ROOT, journal=journal)), runs


def test_health(api):
    c, _ = api
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["contracts_version"] == CONTRACTS_VERSION and h["kpis"] == 6


def test_run_the_analyst_then_read_everything(api):
    c, _ = api
    assert c.get("/api/runs/dev_001/analysis").status_code == 404           # not computed yet
    r = c.post("/api/runs/dev_001/analysis", json={"llm": False}).json()
    assert r["agent"]["status"] == "success"
    assert r["result"]["kpi"] == "Revenue@2.0" and r["result"]["value_current"] == 400.0
    assert all(v["passed"] for v in r["result"]["validations"])

    rows = c.get("/api/runs/dev_001/analysis/rows").json()
    assert rows["columns"] == ["customer_state", "period", "value"]
    assert {"customer_state": "SP", "period": "current", "value": 280.0} in rows["rows"]

    ins = c.get("/api/runs/dev_001/analysis/insights").json()
    assert ins["source"] == "fallback" and ins["insights"]               # LLM down: fixed sentences


def test_insights_from_a_fake_llm_are_marked_llm(api, monkeypatch):
    c, _ = api
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    replies = [
        {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                     "function": {"name": "done", "arguments": "{}"}}]}}]},
        {"choices": [{"message": {"content": json.dumps({"insights": [
            {"text": "Revenue grew by +100.00 BRL.", "facts": ["F1"]}]})}}]}]
    monkeypatch.setattr(llm, "_post", lambda *a, **k: replies.pop(0))
    c.post("/api/runs/dev_001/analysis", json={"llm": True})
    ins = c.get("/api/runs/dev_001/analysis/insights").json()
    assert ins["source"] == "llm" and ins["insights"][0]["text"] == "Revenue grew by +100.00 BRL."


def test_catalog_glossary_and_preview(api):
    c, _ = api
    assert [k["name"] for k in c.get("/api/catalog").json()["kpis"]][:2] == ["Revenue", "Orders"]
    assert any(t["term"] == "AverageBasket" for t in c.get("/api/glossary").json()["terms"])
    p = c.post("/api/kpis/preview", json={"run_id": "dev_001", "metric": "AverageBasket",
                                          "period": AUGUST, "compare_to": JULY}).json()
    values = {r["period"]: round(r["value"], 2) for r in p["rows"]}
    assert p["kpi"] == "AverageBasket@1.0" and values == {"current": 133.33, "previous": 150.0}
    assert all(v["passed"] for v in p["validations"])


def test_refusals(api):
    c, _ = api
    bad_dim = c.post("/api/kpis/preview", json={"run_id": "dev_001", "metric": "Revenue",
                                                "dimensions": ["product_category"], "period": AUGUST})
    assert bad_dim.status_code == 400 and "not allowed" in bad_dim.json()["detail"]
    assert c.get("/api/runs/nope/analysis").status_code == 404
    assert c.get("/api/runs/..%2Fetc/analysis").status_code in (404, 422)     # cannot leave runs/


def test_kpi_proposal_is_a_draft(api):
    c, runs = api
    p = c.post("/api/runs/dev_001/kpi-proposal", json={"llm": False}).json()
    assert p["source"] == "mechanical"
    revenue = next(k for k in p["catalog"]["kpis"] if k["expression"] == "SUM(payment_value)")
    assert revenue["name"] == "Revenue" and revenue["version"] == "2.0"     # approved KPI kept
    assert c.get("/api/catalog").json()["version"] == "1.1"                 # nothing written
