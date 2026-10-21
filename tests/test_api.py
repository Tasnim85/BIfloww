"""Step 6: the HTTP API, on the clinics dataset (temporary folder, no Olist, no LLM).
python -m pytest tests/test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from auditor.agent import run as run_auditor
from auditor.dev import clinics
from comparisons.checker import run as run_checker
from contracts.audit import read_events
from contracts.common import CONTRACTS_VERSION
from contracts.llm import LLMUnavailable, ToolCall
from contracts.pipeline import context_for

RUN = "clinic_001"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    runs = root / "runs"
    clinics.write_run(root, RUN, clinics.visits())
    journal = runs / "clinics_journal.db"
    kw = {"runs_root": runs, "repo_root": root, "journal": journal}
    run_checker(context_for("comparisons", RUN, params={"llm": False}, **kw))
    run_auditor(context_for("auditor", RUN, params={"n_normal": 5}, **kw))
    moves = {}                                    # question -> scripted tool calls (fake LLM)

    def fake_llm(messages, tools, **_):
        return next(moves["it"]), {"role": "assistant", "content": ""}

    def no_writer(*a, **k):
        raise LLMUnavailable("none")

    client = TestClient(create_app(runs_root=runs, repo_root=root, llm=fake_llm, writer=no_writer))
    return client, runs, journal, moves


def test_health_and_runs(world):
    c, *_ = world
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["contracts_version"] == CONTRACTS_VERSION and h["journals"] == ["clinics"]
    runs = c.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == [RUN]
    assert runs[0]["journal"] == "clinics" and runs[0]["has"]["comparison"] and runs[0]["has"]["explanations"]


def test_summary_of_a_blocked_run(world):
    c, *_ = world
    s = c.get(f"/api/runs/{RUN}").json()
    assert s["request"]["metric"] == "Consultation revenue"
    assert s["dashboard"] == {"periods_source": "waiting_for_user", "period": None, "compare_to": None}
    assert s["integrity"]["ok"] and s["anomalies"] > 0 and s["drift_status"] == "not_available"
    assert c.get(f"/api/runs/{RUN}/dashboard").status_code == 409          # nothing shown before the decision


def test_decision_drives_the_dashboard_and_is_journaled(world):
    c, runs, journal, _ = world
    fix = c.get(f"/api/runs/{RUN}/comparison").json()["proposed_fix"]
    r = c.post(f"/api/runs/{RUN}/comparison/decision", json={"decision": "accepted", "chosen_fix": "same_days"})
    assert r.status_code == 200 and r.json()["user_decision"] == "accepted"
    d = c.get(f"/api/runs/{RUN}/dashboard").json()
    assert d["periods_source"] == "fix:same_days" and d["unit"] == "TND"
    assert d["period"] == {"start": "2024-03-01", "end": "2024-03-13"}
    assert d["total_current"] == pytest.approx(fix["value_current"], abs=0.01)
    assert {row["label"] for row in d["rows"]} >= {"Tunis", "Gabes"}
    assert read_events(journal, run_id=RUN)[-1].step == "user_decision"

    assert c.post(f"/api/runs/{RUN}/comparison/decision", json={"decision": "rejected"}).status_code == 200
    assert c.get(f"/api/runs/{RUN}/dashboard").json()["periods_source"] == "as_asked_by_user"
    c.post(f"/api/runs/{RUN}/comparison/decision", json={"decision": "pending"})
    assert c.get(f"/api/runs/{RUN}/dashboard").status_code == 409
    assert c.get("/api/journals/clinics/verify").json()["ok"]


def test_a_fix_that_was_not_offered_is_refused(world):
    c, *_ = world
    r = c.post(f"/api/runs/{RUN}/comparison/decision", json={"decision": "accepted", "chosen_fix": "convert_unit"})
    assert r.status_code == 400 and "not offered" in r.json()["detail"]


def test_new_comparison_on_existing_data(world):
    c, runs, *_ = world
    body = {"base_run": RUN, "metric": "Consultation revenue", "dimensions": ["region"],
            "period": {"start": "2024-01-01", "end": "2024-01-31"},
            "compare_to": {"start": "2023-12-01", "end": "2023-12-31"}}
    r = c.post("/api/comparisons", json=body)
    assert r.status_code == 200
    new = r.json()["run_id"]
    assert new.startswith("custom_") and r.json()["report"]["has_comparison"]
    assert all(ch["status"] != "blocking" for ch in r.json()["report"]["checks"])
    assert c.get(f"/api/runs/{new}/dashboard").json()["periods_source"] == "as_asked"
    assert c.get(f"/api/runs/{new}").json()["journal"] == "ui"               # never the real journal
    assert (runs / new / "static" / "kpi" / "catalog.yaml").exists() is False   # base uses the repo catalog

    assert c.post("/api/comparisons", json={**body, "metric": "Nope"}).status_code == 400
    assert c.post("/api/comparisons", json={**body, "dimensions": ["city"]}).status_code == 400
    assert c.post("/api/comparisons", json={**body, "base_run": "nothing_here"}).status_code == 404


def test_explanations(world):
    c, *_ = world
    page = c.get(f"/api/runs/{RUN}/explanations", params={"limit": 3}).json()
    assert page["total"] > 3 and len(page["items"]) == 3 and page["model_version"] == "iforest-clinics@1.0"
    first = page["items"][0]
    one = c.get(f"/api/runs/{RUN}/explanations/{first['row_key']}").json()
    assert one["narrative"] == first["narrative"] and "TND" in one["narrative"]
    assert c.get(f"/api/runs/{RUN}/explanations/NOPE").status_code == 404


def test_why_agent_over_http(world):
    c, _, journal, moves = world
    cov = next(e.entry_id for e in read_events(journal, run_id=RUN) if e.step == "check_coverage")
    moves["it"] = iter([ToolCall(name="search_journal", args={"step": "check_coverage"}, id="a"),
                        ToolCall(name="final_answer", id="b", args={
                            "answer": f"Bloqué (#{cov}) : mars n'est complet que jusqu'au 2024-03-13.",
                            "citations": [cov]})])
    a = c.post(f"/api/runs/{RUN}/why", json={"question": "Pourquoi la comparaison a-t-elle été bloquée ?"}).json()
    assert a["verified"] and a["citations"] == [cov] and a["tool_calls"][0]["tool"] == "search_journal"
    assert c.post(f"/api/runs/{RUN}/why", json={"question": "?"}).status_code == 422      # too short


def test_journal_routes(world):
    c, *_ = world
    j = c.get("/api/journals").json()
    assert {x["id"] for x in j} >= {"clinics", "ui"} and all(x["intact"] for x in j)
    steps = [e["step"] for e in c.get(f"/api/runs/{RUN}/journal").json()]
    assert "check_coverage" in steps and not any(s.startswith("llm:") for s in steps)
    assert len(c.get("/api/journals/clinics/entries", params={"agent": "auditor"}).json()) > 0
    assert c.get("/api/journals/secret/verify").status_code == 422          # only the known journals


def test_run_ids_cannot_leave_runs(world):
    c, *_ = world
    assert c.get("/api/runs/..%2F..%2Fetc/comparison").status_code in (404, 422)
    assert c.get("/api/runs/a.b/comparison").status_code == 422
    assert c.get("/api/runs/unknown/comparison").status_code == 404


def test_drift_routes(world):
    c, *_ = world
    assert c.get(f"/api/runs/{RUN}/drift").json()["status"] == "not_available"
    assert c.get("/api/drift").json() == []


def test_openapi_lists_every_route(world):
    paths = world[0].get("/openapi.json").json()["paths"]
    for p in ["/runs/{run_id}", "/runs/{run_id}/comparison/decision", "/comparisons",
              "/runs/{run_id}/dashboard", "/runs/{run_id}/why", "/journals/{journal_id}/verify", "/drift"]:
        assert "/api" + p in paths


# ---- integration in the team app --------------------------------------------------------
def test_the_team_app_mounts_the_router_in_one_line(world):
    from fastapi import FastAPI

    from api.router import make_router
    _, runs, *_ = world
    team = FastAPI()
    team.include_router(make_router(runs_root=runs, repo_root=runs.parent), prefix="/api")
    t = TestClient(team)
    assert t.get(f"/api/runs/{RUN}").json()["run_id"] == RUN          # same URLs as standalone


def test_demo_journals_can_be_hidden_in_production(world, monkeypatch):
    _, runs, *_ = world
    monkeypatch.setenv("BIFLOW_JOURNALS", "real,ui")
    app = create_app(runs_root=runs, repo_root=runs.parent)
    c = TestClient(app)
    assert {j["id"] for j in c.get("/api/journals").json()} == {"ui"}       # clinics hidden
    assert c.get("/api/journals/clinics/verify").status_code == 422
    assert c.get("/health").json()["journals"] == ["ui"]


def test_datasets_lists_the_data_that_can_answer_new_questions(world):
    c, *_ = world
    d = c.get("/api/datasets").json()
    clinic = next(x for x in d if x["run_id"] == RUN)
    assert clinic["first_day"] == "2023-10-01" and clinic["last_day"] == "2024-03-20"
    assert clinic["kpis"][0]["name"] == "Consultation revenue" and clinic["kpis"][0]["unit"] == "TND"
    assert "region" in clinic["dimensions"]
    assert not any(x["run_id"].startswith("custom_") for x in d)
