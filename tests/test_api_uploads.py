"""Samar's intake + dashboard in the app: the user's own CSV files through the whole DAG, with the
reviews answered over HTTP. Uses the TEST DOUBLE of Ollama (in-process), never a real model.
python -m pytest tests/test_api_uploads.py -v
"""
import socket
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import contracts.llm as llm
from api.jobs import safe_name
from api.main import create_app
from contracts.audit import read_events, verify_journal
from contracts.pipeline import REPO_ROOT

SAMPLE = REPO_ROOT / "data" / "sample"
QUESTION = "Revenue by customer state, August 2018 vs July 2018"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def fake_ollama():
    from tools.integration.fake_ollama import H, ThreadingHTTPServer
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture
def api(tmp_path, monkeypatch, fake_ollama):
    monkeypatch.setenv("OLLAMA_BASE_URL", fake_ollama)
    monkeypatch.setenv("BO2_PII_SECRET", "t" * 40)
    monkeypatch.setattr(llm, "_post", lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("off")))
    runs = tmp_path / "runs"
    runs.mkdir()
    return TestClient(create_app(runs_root=runs, repo_root=REPO_ROOT)), runs


def csv_files(folder: Path = SAMPLE):
    return [("files", (p.name, p.read_bytes(), "text/csv")) for p in sorted(folder.glob("*.csv"))]


def wait(c, rid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = c.get(f"/api/runs/{rid}/progress").json()
        if p["state"] != "running":
            return p
        time.sleep(0.5)
    raise AssertionError("pipeline did not stop")


@pytest.mark.skipif(not SAMPLE.exists(), reason="data/sample is missing")
def test_upload_runs_the_whole_dag_with_the_reviews_answered_in_the_app(api):
    c, runs = api
    assert c.get("/health").json()["test_double"] is True
    r = c.post("/api/uploads", files=csv_files(), data={"question": QUESTION, "lang": "en"})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    assert rid.startswith("up_") and "olist_orders_dataset" in r.json()["tables"]
    seen = []
    for _ in range(6):
        p = wait(c, rid)
        if p["state"] != "needs_review":
            break
        rv = p["review"]
        seen.append(rv["step"])
        if rv["step"] == "etl":
            assert rv["tables"] and any(t["role"] == "fact" for t in rv["tables"]) and rv["links"]
            assert str(runs) not in str(rv)                         # no local path
            assert c.post(f"/api/runs/{rid}/review", json={"step": "etl", "decision": "approve"}).status_code == 200
        elif rv["step"] == "pii":
            assert c.post(f"/api/runs/{rid}/review", json={"step": "pii", "decision": "approve"}).status_code == 200
        else:
            fix = c.get(f"/api/runs/{rid}/comparison").json()["proposed_fix"]["method"]
            assert c.post(f"/api/runs/{rid}/comparison/decision",
                          json={"decision": "accepted", "chosen_fix": fix}).status_code == 200
    assert p["state"] == "done", p
    assert "etl" in seen
    view = c.get(f"/api/runs/{rid}/pipeline").json()
    assert all(s["available"] for s in view["stages"]) and view["base_run"] == rid
    charts = c.get(f"/api/runs/{rid}/charts").json()
    assert {x["chart_type"] for x in charts["charts"]} >= {"kpi_card"} and charts["charts"][0]["rows"]
    assert str(runs) not in str(charts)
    # the test double's decisions are in their own journal, never in the real one
    assert not (runs / "audit_journal.db").exists()
    journal = runs / "integration_journal.db"
    assert verify_journal(journal).ok
    reviews = [e for e in read_events(journal, run_id=rid) if e.step == "human_review"]
    assert reviews and reviews[0].decision.startswith("APPROVED")
    # a user's data is never offered to the others
    assert rid not in [d["run_id"] for d in c.get("/api/datasets").json()]


def test_upload_refuses_what_is_not_a_clean_csv(api):
    c, _ = api
    bad = c.post("/api/uploads", files=[("files", ("evil.exe", b"MZ", "application/octet-stream"))], data={"question": QUESTION})
    assert bad.status_code == 400
    empty = c.post("/api/uploads", files=[("files", ("a.csv", b"  ", "text/csv"))], data={"question": QUESTION})
    assert empty.status_code == 400
    twice = c.post("/api/uploads", files=[("files", ("a.csv", b"x\n1", "text/csv")), ("files", ("A.csv", b"x\n1", "text/csv"))],
                   data={"question": QUESTION})
    assert twice.status_code == 400
    assert c.post("/api/uploads", files=[("files", ("a.csv", b"x\n1", "text/csv"))], data={"question": "a"}).status_code == 422


def test_safe_names():
    assert safe_name("../../etc/passwd.csv") == "passwd.csv"
    assert safe_name("C:\\Users\\x\\Ventes 2024 (v2).csv") == "Ventes_2024_v2.csv"
    assert safe_name("report.csv.exe") is None and safe_name(".csv") is None


def test_no_secret_no_run(api, monkeypatch):
    c, runs = api
    monkeypatch.setenv("BO2_PII_SECRET", "short")
    r = c.post("/api/uploads", files=[("files", ("a.csv", b"x\n1", "text/csv"))], data={"question": QUESTION})
    assert r.status_code == 503 and "BO2_PII_SECRET" in r.json()["detail"]
    assert list(runs.iterdir()) == []


def test_progress_and_review_only_for_uploaded_runs(api):
    c, _ = api
    assert c.get("/api/runs/run_001/progress").status_code == 404
    assert c.get("/api/runs/up_000000000000/progress").status_code == 404
    assert c.post("/api/runs/run_001/review", json={"step": "etl", "decision": "approve"}).status_code == 404
