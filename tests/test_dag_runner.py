"""tests/test_dag_runner.py — Tests de l'orchestrateur DAG avec agents stub.

Couvre :
  T01 - Parallelisme reel (2 taches independantes < 0.45 s avec max_workers=2)
  T02 - Barriere de dependance (step C attend A et B)
  T03 - max_workers=1 force la serialisation
  T04 - Persistance SQLite (etats PENDING puis SUCCESS)
  T05 - Reprise (step deja SUCCESS non re-execute)
  T06 - Fail -> Skip downstream
  T07 - ModuleNotFoundError -> SKIPPED (pas FAILED)
  T08 - CycleError: le DAG detecte bien les cycles (comportement verifie)

ARCHITECTURE NOTE:
  _execute_step() appelle context_for() depuis contracts.pipeline, qui lit STEPS.
  Pour isoler les tests, on patche aussi context_for pour retourner un RunContext minimal.
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from unittest import mock
import uuid

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contracts.agent import AgentResult, AgentStatus, RunContext
from orchestrator.task_store import TaskStatus, init_run, get_status, set_done
from contracts.audit import DEFAULT_JOURNAL


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_run_id() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


def _stub_result(run_id: str, agent: str, status: AgentStatus = AgentStatus.SUCCESS,
                 message: str = "stub ok") -> AgentResult:
    return AgentResult(run_id=run_id, agent=agent, status=status, message=message)


def _make_step(name: str, depends_on: set, entrypoint: str = "stub", outputs=None):
    step = mock.MagicMock()
    step.name = mock.MagicMock()
    step.name.value = name
    step.entrypoint = entrypoint
    step.depends_on = set(depends_on)
    step.outputs = outputs or {}
    step.after = []
    step.inputs = {}
    return step


def _make_ctx(run_id: str, step: str, runs_root: Path) -> RunContext:
    """Minimal RunContext for stub agents."""
    output_dir = runs_root / run_id / step
    output_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        run_id=run_id,
        agent=step,
        inputs={},
        output_dir=output_dir,
        params={},
        journal=Path("runs/audit.jsonl"),
    )


@pytest.fixture()
def tmp_dirs(tmp_path):
    db = tmp_path / "tasks.db"
    runs = tmp_path / "runs"
    runs.mkdir()
    return tmp_path, db, runs


# ── Patch helper ─────────────────────────────────────────────────────────────

class _PipelineContext:
    """Patches STEPS, graph(), and context_for() in dag_runner together."""

    def __init__(self, steps, dag, runs, run_id):
        self._steps = steps
        self._dag = dag
        self._runs = runs
        self._run_id = run_id
        self._patches = []

    def _fake_context_for(self, step_name, run_id, runs_root=None, repo_root=None,
                          journal=None, params=None):
        return _make_ctx(run_id, step_name, self._runs)

    def __enter__(self):
        import orchestrator.dag_runner as runner
        self._patches = [
            mock.patch.object(runner, "STEPS", self._steps),
            mock.patch("orchestrator.dag_runner.graph", return_value=self._dag),
            mock.patch("orchestrator.dag_runner.context_for",
                       side_effect=self._fake_context_for),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.stop()


# ═══════════════════════════════════════════════════════════════════════════
# T01 — Parallelisme reel avec max_workers=2
# ═══════════════════════════════════════════════════════════════════════════

def test_t01_parallel_execution(tmp_dirs):
    """2 taches independantes de 0.25 s doivent finir en < 0.45 s avec max_workers=2."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()
    lock = threading.Lock()
    timings = {}

    def make_slow(name, delay=0.25):
        def agent(ctx):
            time.sleep(delay)
            with lock:
                timings[name] = True
            return _stub_result(run_id, name)
        return agent

    step_A = _make_step("A", set(), "ep_A")
    step_B = _make_step("B", set(), "ep_B")
    steps = {"A": step_A, "B": step_B}
    dag = {"A": set(), "B": set()}

    import orchestrator.dag_runner as runner
    agents = {"ep_A": make_slow("A"), "ep_B": make_slow("B")}

    def fake_import(ep):
        return agents.get(ep, lambda ctx: _stub_result(run_id, "?"))

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=fake_import):
            t0 = time.time()
            runner.run_pipeline(run_id=run_id, max_workers=2, runs_root=runs, db=db)
            elapsed = time.time() - t0

    assert elapsed < 0.45, f"Parallelisme attendu, elapsed={elapsed:.3f}s"
    assert "A" in timings and "B" in timings


# ═══════════════════════════════════════════════════════════════════════════
# T02 — Barriere de dependance : C attend A ET B
# ═══════════════════════════════════════════════════════════════════════════

def test_t02_dependency_barrier(tmp_dirs):
    """C ne demarre pas avant que A et B soient termines."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()
    lock = threading.Lock()
    finish_times = {}

    def timed(name, delay=0.0):
        def agent(ctx):
            time.sleep(delay)
            with lock:
                finish_times[name] = time.time()
            return _stub_result(run_id, name)
        return agent

    step_A = _make_step("A", set(), "ep_A")
    step_B = _make_step("B", set(), "ep_B")
    step_C = _make_step("C", {"A", "B"}, "ep_C")
    steps = {"A": step_A, "B": step_B, "C": step_C}
    dag = {"A": set(), "B": set(), "C": {"A", "B"}}

    import orchestrator.dag_runner as runner
    agents = {"ep_A": timed("A", 0.1), "ep_B": timed("B", 0.1), "ep_C": timed("C")}

    def fake_import(ep):
        return agents.get(ep, lambda ctx: _stub_result(run_id, "?"))

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=fake_import):
            runner.run_pipeline(run_id=run_id, max_workers=4, runs_root=runs, db=db)

    assert finish_times["C"] >= finish_times["A"], "C a demarre avant A"
    assert finish_times["C"] >= finish_times["B"], "C a demarre avant B"


# ═══════════════════════════════════════════════════════════════════════════
# T03 — max_workers=1 serialise les etapes
# ═══════════════════════════════════════════════════════════════════════════

def test_t03_max_workers_1_serializes(tmp_dirs):
    """Avec max_workers=1, A + B (chacun 0.15 s) prennent > 0.28 s."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    def slow(ctx):
        time.sleep(0.15)
        return _stub_result(run_id, "x")

    step_A = _make_step("A", set(), "ep_X")
    step_B = _make_step("B", set(), "ep_X")
    steps = {"A": step_A, "B": step_B}
    dag = {"A": set(), "B": set()}

    import orchestrator.dag_runner as runner

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", return_value=slow):
            t0 = time.time()
            runner.run_pipeline(run_id=run_id, max_workers=1, runs_root=runs, db=db)
            elapsed = time.time() - t0

    assert elapsed >= 0.28, f"max_workers=1 doit serialiser, elapsed={elapsed:.3f}s"


# ═══════════════════════════════════════════════════════════════════════════
# T04 — Persistance SQLite : etats PENDING puis SUCCESS
# ═══════════════════════════════════════════════════════════════════════════

def test_t04_sqlite_persistence(tmp_dirs):
    """Apres init_run -> PENDING ; apres run_pipeline -> SUCCESS dans SQLite."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "ep_ok")
    steps = {"A": step_A}
    dag = {"A": set()}

    init_run(run_id, ["A"], db=db)
    assert get_status(run_id, "A", db=db) == TaskStatus.PENDING

    import orchestrator.dag_runner as runner

    def ok_agent(ctx):
        return _stub_result(run_id, "A")

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", return_value=ok_agent):
            runner.run_pipeline(run_id=run_id, max_workers=2, runs_root=runs, db=db)

    assert get_status(run_id, "A", db=db) == TaskStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════════════════
# T05 — Reprise : step SUCCESS non re-execute
# ═══════════════════════════════════════════════════════════════════════════

def test_t05_resume_skips_done_steps(tmp_dirs):
    """Un step deja SUCCESS en DB n'est pas re-execute."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()
    call_count = [0]

    step_A = _make_step("A", set(), "ep_count", outputs={})
    steps = {"A": step_A}
    dag = {"A": set()}

    init_run(run_id, ["A"], db=db)
    set_done(run_id, "A", TaskStatus.SUCCESS, "pre-existing", db=db)

    import orchestrator.dag_runner as runner

    def counting(ctx):
        call_count[0] += 1
        return _stub_result(run_id, "A")

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", return_value=counting):
            results = runner.run_pipeline(run_id=run_id, max_workers=2,
                                          runs_root=runs, db=db)

    assert call_count[0] == 0, f"Agent appele {call_count[0]} fois malgre SUCCESS en DB"
    assert results["A"].status == AgentStatus.SUCCESS


# ═══════════════════════════════════════════════════════════════════════════
# T06 — Fail -> Skip downstream
# ═══════════════════════════════════════════════════════════════════════════

def test_t06_fail_skips_downstream(tmp_dirs):
    """Si A echoue, B (qui depend de A) est SKIPPED."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "ep_fail")
    step_B = _make_step("B", {"A"}, "ep_ok")
    steps = {"A": step_A, "B": step_B}
    dag = {"A": set(), "B": {"A"}}

    import orchestrator.dag_runner as runner

    def fail_agent(ctx):
        return _stub_result(run_id, "A", AgentStatus.FAILED, "forced")

    def ok_agent(ctx):
        return _stub_result(run_id, "B")

    def fake_import(ep):
        return fail_agent if ep == "ep_fail" else ok_agent

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=fake_import):
            results = runner.run_pipeline(run_id=run_id, max_workers=2,
                                          runs_root=runs, db=db, stop_on_failure=True)

    assert results["A"].status == AgentStatus.FAILED
    assert results["B"].status == AgentStatus.SKIPPED, (
        f"B devrait etre SKIPPED, got {results['B'].status}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# T07 — ModuleNotFoundError -> SKIPPED
# ═══════════════════════════════════════════════════════════════════════════

def test_t07_module_not_found_gives_skipped(tmp_dirs):
    """Entrypoint de module inexistant -> SKIPPED (pas FAILED)."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "totally.nonexistent.module:run")
    steps = {"A": step_A}
    dag = {"A": set()}

    import orchestrator.dag_runner as runner

    # Use real _import_run (raises ModuleNotFoundError caught by _execute_step)
    with _PipelineContext(steps, dag, runs, run_id):
        results = runner.run_pipeline(run_id=run_id, max_workers=2,
                                      runs_root=runs, db=db)

    assert results["A"].status == AgentStatus.SKIPPED, (
        f"Attendu SKIPPED pour module absent, got {results['A'].status}: {results['A'].message}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# T08 — Cycle detecte par le DAG
# ═══════════════════════════════════════════════════════════════════════════

def test_t08_cycle_raises_error(tmp_dirs):
    """Un DAG cyclique doit lever RuntimeError ou CycleError avant toute execution."""
    from graphlib import CycleError
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", {"B"}, "ep_A")
    step_B = _make_step("B", {"A"}, "ep_B")
    steps = {"A": step_A, "B": step_B}
    dag = {"A": {"B"}, "B": {"A"}}

    import orchestrator.dag_runner as runner

    # dag_runner wraps CycleError at static_order() but the second sorter.prepare()
    # also raises CycleError; accept both RuntimeError and CycleError.
    with _PipelineContext(steps, dag, runs, run_id):
        with pytest.raises((RuntimeError, CycleError)):
            runner.run_pipeline(run_id=run_id, max_workers=2,
                                runs_root=runs, db=db)


# ═══════════════════════════════════════════════════════════════════════════
# T09 — Internal dependency ModuleNotFoundError -> FAILED (not SKIPPED)
# ═══════════════════════════════════════════════════════════════════════════

def test_t09_internal_dependency_missing_gives_failed(tmp_dirs):
    """Un ModuleNotFoundError declenche par une dependance interne d'un agent doit FAILED, pas SKIPPED."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "existing_agent.module:run")
    steps = {"A": step_A}
    dag = {"A": set()}

    import orchestrator.dag_runner as runner

    def fake_import(ep):
        err = ModuleNotFoundError("No module named 'missing_internal_pkg'")
        err.name = "missing_internal_pkg"
        raise err

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=fake_import):
            results = runner.run_pipeline(run_id=run_id, max_workers=2,
                                          runs_root=runs, db=db)

    assert results["A"].status == AgentStatus.FAILED, (
        f"Une dependance interne manquante doit FAILED (pas SKIPPED), got {results['A'].status}: {results['A'].message}"
    )
    assert "missing_internal_pkg" in results["A"].message


# ═══════════════════════════════════════════════════════════════════════════
# T10 — NEEDS_REVIEW bloque les dépendants
# ═══════════════════════════════════════════════════════════════════════════

def test_t10_needs_review_blocks_downstream(tmp_dirs):
    """Si A renvoie NEEDS_REVIEW, B (dépendant de A) ne doit PAS s'exécuter."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "ep_review")
    step_B = _make_step("B", {"A"}, "ep_consumer")
    steps = {"A": step_A, "B": step_B}
    dag = {"A": set(), "B": {"A"}}

    import orchestrator.dag_runner as runner

    def review_agent(ctx):
        return _stub_result(run_id, "A", AgentStatus.NEEDS_REVIEW, "requires review")

    b_executed = [False]
    def consumer_agent(ctx):
        b_executed[0] = True
        return _stub_result(run_id, "B", AgentStatus.SUCCESS, "ok")

    def dispatch(ep):
        return review_agent if ep == "ep_review" else consumer_agent

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=dispatch):
            results = runner.run_pipeline(run_id=run_id, max_workers=2, runs_root=runs, db=db)

    assert results["A"].status == AgentStatus.NEEDS_REVIEW
    assert results["B"].status == AgentStatus.SKIPPED
    assert "review" in results["B"].message.lower()
    assert not b_executed[0], "B ne doit pas s'exécuter si A est NEEDS_REVIEW"


# ═══════════════════════════════════════════════════════════════════════════
# T11 — Propagation transitive de l'échec (A -> B -> C)
# ═══════════════════════════════════════════════════════════════════════════

def test_t11_transitive_failure_skips_full_chain(tmp_dirs):
    """Dans A -> B -> C, si A échoue, B est SKIPPED et C est également SKIPPED."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "ep_a")
    step_B = _make_step("B", {"A"}, "ep_b")
    step_C = _make_step("C", {"B"}, "ep_c")
    steps = {"A": step_A, "B": step_B, "C": step_C}
    dag = {"A": set(), "B": {"A"}, "C": {"B"}}

    import orchestrator.dag_runner as runner

    def fail_a(ctx):
        return _stub_result(run_id, "A", AgentStatus.FAILED, "error in A")

    c_executed = [False]
    def agent_c(ctx):
        c_executed[0] = True
        return _stub_result(run_id, "C", AgentStatus.SUCCESS, "ok")

    def dispatch(ep):
        if ep == "ep_a":
            return fail_a
        return agent_c

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=dispatch):
            results = runner.run_pipeline(run_id=run_id, max_workers=2, runs_root=runs, db=db)

    assert results["A"].status == AgentStatus.FAILED
    assert results["B"].status == AgentStatus.SKIPPED
    assert results["C"].status == AgentStatus.SKIPPED
    assert not c_executed[0], "C ne doit pas s'exécuter si son ancêtre a échoué"


# ═══════════════════════════════════════════════════════════════════════════
# T12 — Agent non implémenté / manquant bloque les consommateurs
# ═══════════════════════════════════════════════════════════════════════════

def test_t12_missing_agent_skips_downstream_consumer(tmp_dirs):
    """Si A est SKIPPED car non implémenté, B qui consomme A doit être SKIPPED."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "missing_pkg.agent:run")
    step_B = _make_step("B", {"A"}, "ep_b")
    steps = {"A": step_A, "B": step_B}
    dag = {"A": set(), "B": {"A"}}

    import orchestrator.dag_runner as runner

    b_executed = [False]
    def agent_b(ctx):
        b_executed[0] = True
        return _stub_result(run_id, "B", AgentStatus.SUCCESS, "ok")

    def fake_import(ep):
        if ep == "missing_pkg.agent:run":
            raise ModuleNotFoundError("No module named 'missing_pkg'", name="missing_pkg")
        return agent_b

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=fake_import):
            results = runner.run_pipeline(run_id=run_id, max_workers=2, runs_root=runs, db=db)

    assert results["A"].status == AgentStatus.SKIPPED
    assert results["B"].status == AgentStatus.SKIPPED
    assert not b_executed[0], "B ne doit pas s'exécuter si A est manquant"


# ═══════════════════════════════════════════════════════════════════════════
# T13 — SUCCESS sans artefact obligatoire converti en FAILED
# ═══════════════════════════════════════════════════════════════════════════

def test_t13_success_without_outputs_fails_and_skips_downstream(tmp_dirs):
    """Si A déclare SUCCESS sans créer son fichier de sortie obligatoire, A échoue et B est SKIPPED."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "ep_a", outputs={"report": "report.json"})
    step_B = _make_step("B", {"A"}, "ep_b")
    steps = {"A": step_A, "B": step_B}
    dag = {"A": set(), "B": {"A"}}

    import orchestrator.dag_runner as runner

    # A déclare SUCCESS mais n'écrit pas report.json
    def bad_agent_a(ctx):
        return _stub_result(run_id, "A", AgentStatus.SUCCESS, "claimed success but wrote nothing")

    b_executed = [False]
    def agent_b(ctx):
        b_executed[0] = True
        return _stub_result(run_id, "B", AgentStatus.SUCCESS, "ok")

    def dispatch(ep):
        return bad_agent_a if ep == "ep_a" else agent_b

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=dispatch):
            results = runner.run_pipeline(run_id=run_id, max_workers=2, runs_root=runs, db=db)

    assert results["A"].status == AgentStatus.FAILED
    assert "without producing valid artifact" in results["A"].message.lower() or "missing declared output artifact" in results["A"].message.lower()
    assert results["B"].status == AgentStatus.SKIPPED
    assert not b_executed[0], "B ne doit pas s'exécuter si les artefacts requis de A sont absents"


# ???????????????????????????????????????????????????????????????????????????
# T14 ? Ancien SUCCESS invalid? si une d?pendance amont n?cessite une nouvelle revue
# ???????????????????????????????????????????????????????????????????????????

def test_t14_resume_invalidated_when_upstream_not_success(tmp_dirs):
    """Si B ?tait SUCCESS dans la DB, mais que A renvoie maintenant NEEDS_REVIEW,
    B ne doit PAS ?tre r?utilis? en SUCCESS : il doit ?tre suspendu / SKIPPED."""
    tmp_path, db, runs = tmp_dirs
    run_id = _make_run_id()

    step_A = _make_step("A", set(), "ep_a", outputs={"report": "a.json"})
    step_B = _make_step("B", {"A"}, "ep_b", outputs={"report": "b.json"})
    steps = {"A": step_A, "B": step_B}
    dag = {"A": set(), "B": {"A"}}

    init_run(run_id, ["A", "B"], db=db)
    # Simuler un run pr?c?dent o? B ?tait SUCCESS
    set_done(run_id, "B", TaskStatus.SUCCESS, "old success", outputs={"report": "b.json"}, db=db)
    # Cr?er le fichier de sortie de B
    b_out = runs / run_id / "B" / "b.json"
    b_out.parent.mkdir(parents=True, exist_ok=True)
    b_out.write_text('{"status": "old_ok"}', encoding="utf-8")

    import orchestrator.dag_runner as runner

    def review_a(ctx):
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        (ctx.output_dir / "a.json").write_text("{}", encoding="utf-8")
        return _stub_result(run_id, "A", AgentStatus.NEEDS_REVIEW, "requires review")

    b_executed = [False]
    def agent_b(ctx):
        b_executed[0] = True
        return _stub_result(run_id, "B", AgentStatus.SUCCESS, "new ok")

    def dispatch(ep):
        return review_a if ep == "ep_a" else agent_b

    with _PipelineContext(steps, dag, runs, run_id):
        with mock.patch.object(runner, "_import_run", side_effect=dispatch):
            results = runner.run_pipeline(run_id=run_id, max_workers=2, runs_root=runs, db=db)

    assert results["A"].status == AgentStatus.NEEDS_REVIEW
    # B NE DOIT PAS ?tre r?utilis? en SUCCESS : il doit ?tre SKIPPED car A n'a pas r?ussi !
    assert results["B"].status == AgentStatus.SKIPPED, (
        f"B ne doit pas r?utiliser un ancien SUCCESS si A est NEEDS_REVIEW, got {results['B'].status}"
    )
    assert not b_executed[0]
