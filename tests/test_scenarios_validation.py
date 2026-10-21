import json
import uuid
from pathlib import Path
from unittest import mock
import pandas as pd
import pytest

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import save, load
from contracts.pipeline import STEPS, output_path, execution_order
from orchestrator.dag_runner import run_pipeline, get_run_status
from orchestrator.task_store import TaskStatus, get_status

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_scenario_a_known_synthetic_dataset(tmp_path):
    """Scénario A : Dataset synthétique Olist connu.
    Vérifie la chaîne : Upload -> Similarity -> Column Classification -> Request
    et vérifie les rapports riches (column_matches.json, semantic_metadata.json).
    """
    run_id = f"scen_a_{uuid.uuid4().hex[:6]}"
    runs_root = tmp_path / "runs"
    db_path = tmp_path / f"tasks_{run_id}.db"
    journal = tmp_path / f"journal_{run_id}.jsonl"

    params = {
        "source_dir": str(REPO_ROOT / "data" / "sample"),
        "question": "Revenue by state in August",
        "uploaded_by": "ScenarioATester",
    }

    # Run upload, similarity, column_types, request
    results = run_pipeline(
        run_id=run_id,
        runs_root=runs_root,
        journal=journal,
        db=db_path,
        params=params,
        stop_on_failure=False,
    )

    # 1. Upload
    assert results["upload"].status == AgentStatus.SUCCESS
    up_path = output_path(run_id, "upload", "upload", runs_root=runs_root)
    assert up_path.exists()
    up_data = json.loads(up_path.read_text(encoding="utf-8"))
    assert len(up_data["tables"]) >= 8

    # 2. Similarity
    assert results["similarity"].status == AgentStatus.SUCCESS
    sim_rep_path = output_path(run_id, "similarity", "report", runs_root=runs_root)
    assert sim_rep_path.exists()
    sim_rep = json.loads(sim_rep_path.read_text(encoding="utf-8"))
    assert sim_rep["best_match"] is not None
    assert sim_rep["best_match"]["name"] == "olist"
    assert sim_rep["best_match"]["score"] > 0.40

    # Cross-table matches
    col_matches_path = output_path(run_id, "similarity", "matches", runs_root=runs_root)
    assert col_matches_path.exists()
    col_matches = json.loads(col_matches_path.read_text(encoding="utf-8"))
    assert col_matches["matches_found"] > 0
    assert col_matches["matches_found"] == len(col_matches["matches"])
    # Check that alignment includes orders <-> order_items order_id
    aligned_pairs = {(m["source_column"], m["target_column"]) for m in col_matches["matches"]}
    assert any("order_id" in s and "order_id" in t for s, t in aligned_pairs)

    # 3. Column Classification (Hybrid Classifier)
    assert results["column_types"].status == AgentStatus.SUCCESS
    ct_path = output_path(run_id, "column_types", "report", runs_root=runs_root)
    assert ct_path.exists()
    meta_path = output_path(run_id, "column_types", "semantic_metadata", runs_root=runs_root)
    assert meta_path.exists()
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_data["total_columns"] >= 50
    # Check key column types
    by_col = {c["column_name"]: c for c in meta_data["columns"]}
    assert by_col["payment_installments"]["semantic_type"] == "QUANTITY"
    assert by_col["customer_unique_id"]["semantic_type"] == "PERSON_ID"
    assert by_col["review_id"]["semantic_type"] == "SYSTEM_ID"

    # 4. Request Understanding
    assert results["request"].status == AgentStatus.SUCCESS
    req_path = output_path(run_id, "request", "request", runs_root=runs_root)
    assert req_path.exists()
    req_data = json.loads(req_path.read_text(encoding="utf-8"))
    assert req_data["metric"] == "Revenue"
    assert req_data["dimensions"] == ["customer_state"]
    assert req_data["period"]["start"] == "2018-08-01"
    assert req_data["period"]["end"] == "2018-08-31"


def test_scenario_b_unknown_dataset_and_request_review(tmp_path):
    """Scénario B : Dataset inconnu et requête inconnue.
    Vérifie qu'un dataset inconnu n'invente pas un playbook et qu'une
    question hors glossaire / catalog produit un NEEDS_REVIEW sans résultat inventé.
    """
    run_id = f"scen_b_{uuid.uuid4().hex[:6]}"
    runs_root = tmp_path / "runs"
    db_path = tmp_path / f"tasks_{run_id}.db"
    journal = tmp_path / f"journal_{run_id}.jsonl"

    # Create dummy unknown dataset
    dummy_dir = tmp_path / "unknown_csvs"
    dummy_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "alpha_xyz": [1, 2, 3],
        "beta_custom_tag": ["foo", "bar", "baz"],
        "mystery_metric_99": [10.5, 20.1, 33.2],
    })
    df.to_csv(dummy_dir / "unknown_table.csv", index=False)

    params = {
        "source_dir": str(dummy_dir),
        "question": "What is the quantum flux of gamma rays in 2099?",
        "uploaded_by": "ScenarioBTester",
    }

    results = run_pipeline(
        run_id=run_id,
        runs_root=runs_root,
        journal=journal,
        db=db_path,
        params=params,
        stop_on_failure=False,
    )

    # 1. Similarity should report low score or None for known playbooks
    sim_res = results["similarity"]
    assert sim_res.status == AgentStatus.SUCCESS
    sim_data = json.loads(output_path(run_id, "similarity", "report", runs_root=runs_root).read_text(encoding="utf-8"))
    # Unknown dataset must have low similarity score (< 0.40) or no playbook
    if sim_data["best_match"] is not None:
        assert sim_data["best_match"]["score"] < 0.40
    else:
        assert sim_data["best_match"] is None

    # 2. Request should trigger NEEDS_REVIEW because KPI is not in catalog
    req_res = results["request"]
    assert req_res.status == AgentStatus.NEEDS_REVIEW
    assert "could not match" in req_res.message.lower() or "reformulate" in req_res.message.lower()


def test_scenario_c_controlled_failure_and_recovery(tmp_path):
    """Scénario C : Échec contrôlé -> blocage des consommateurs -> correction -> reprise.
    """
    run_id = f"scen_c_{uuid.uuid4().hex[:6]}"
    runs_root = tmp_path / "runs"
    db_path = tmp_path / f"tasks_{run_id}.db"
    journal = tmp_path / f"journal_{run_id}.jsonl"

    class StepA:
        should_fail = True
        @classmethod
        def run(cls, ctx):
            if cls.should_fail:
                raise RuntimeError("Controlled failure in Step A")
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            out = ctx.output("upload")
            out.write_text('{"tables": ["t1"]}', encoding="utf-8")
            (ctx.output_dir / "tables").mkdir(parents=True, exist_ok=True)
            return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                               outputs={"upload": out, "tables": ctx.output_dir / "tables"})

    # Patch upload entrypoint to use StepA.run
    with mock.patch("orchestrator.dag_runner._import_run", return_value=StepA.run):
        # Initial run: Step A fails
        results = run_pipeline(
            run_id=run_id,
            runs_root=runs_root,
            journal=journal,
            db=db_path,
            stop_on_failure=False,
        )
        assert results["upload"].status == AgentStatus.FAILED
        # Direct & transitive dependents MUST be SKIPPED
        assert results["similarity"].status == AgentStatus.SKIPPED
        assert results["column_types"].status == AgentStatus.SKIPPED
        assert results["pii"].status == AgentStatus.SKIPPED

    # Fix Step A
    StepA.should_fail = False

    # Resume run on the SAME run_id
    with mock.patch("orchestrator.dag_runner._import_run", return_value=StepA.run):
        resumed_results = run_pipeline(
            run_id=run_id,
            runs_root=runs_root,
            journal=journal,
            db=db_path,
            stop_on_failure=False,
        )
        # Step A re-executes and now succeeds!
        assert resumed_results["upload"].status == AgentStatus.SUCCESS
        assert get_status(run_id, "upload", db=db_path) == TaskStatus.SUCCESS


def test_scenario_d_needs_review_and_approved_resumption(tmp_path):
    """Scénario D : NEEDS_REVIEW -> aucune consommation aval -> approbation valide -> reprise.
    """
    run_id = f"scen_d_{uuid.uuid4().hex[:6]}"
    runs_root = tmp_path / "runs"
    db_path = tmp_path / f"tasks_{run_id}.db"
    journal = tmp_path / f"journal_{run_id}.jsonl"

    class ReviewStep:
        @classmethod
        def run(cls, ctx):
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            out = ctx.output("upload")
            out.write_text('{"status": "review_pending"}', encoding="utf-8")
            (ctx.output_dir / "tables").mkdir(parents=True, exist_ok=True)
            return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.NEEDS_REVIEW,
                               message="Human confirmation required before proceeding",
                               outputs={"upload": out, "tables": ctx.output_dir / "tables"})

    with mock.patch("orchestrator.dag_runner._import_run", return_value=ReviewStep.run):
        results = run_pipeline(
            run_id=run_id,
            runs_root=runs_root,
            journal=journal,
            db=db_path,
            stop_on_failure=False,
        )
        assert results["upload"].status == AgentStatus.NEEDS_REVIEW
        # Downstream tasks MUST be blocked / SKIPPED
        assert results["similarity"].status == AgentStatus.SKIPPED
        assert results["column_types"].status == AgentStatus.SKIPPED
        assert "human review" in results["similarity"].message.lower()

    # Now resume with valid explicit human approval
    approved_reviews = {
        "upload": {
            "decision": "APPROVED",
            "reviewer": "ComplianceOfficer",
            "run_id": run_id,
            "timestamp": "2026-10-21T23:00:00Z"
        }
    }

    class ApprovedStep:
        @classmethod
        def run(cls, ctx):
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            out = ctx.output("upload")
            out.write_text('{"status": "approved"}', encoding="utf-8")
            (ctx.output_dir / "tables").mkdir(parents=True, exist_ok=True)
            return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS,
                               message="Approved and processed successfully",
                               outputs={"upload": out, "tables": ctx.output_dir / "tables"})

    with mock.patch("orchestrator.dag_runner._import_run", return_value=ApprovedStep.run):
        resumed_results = run_pipeline(
            run_id=run_id,
            runs_root=runs_root,
            journal=journal,
            db=db_path,
            approved_reviews=approved_reviews,
            stop_on_failure=False,
        )
        assert resumed_results["upload"].status == AgentStatus.SUCCESS
        assert get_status(run_id, "upload", db=db_path) == TaskStatus.SUCCESS
