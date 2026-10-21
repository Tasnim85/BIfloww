"""Tests of step 3 (BO4-12) on the real Olist data.   python -m pytest tests/test_comparisons.py -v

Needs the fake inputs of step 1:  python -m auditor.dev.make_fake_inputs
Every test writes in a temporary folder with its own journal: runs/ is never touched.
"""
from pathlib import Path

import pytest

from comparisons.checker import record_decision, run
from comparisons.narrate import summarize, unsupported_numbers, allowed_numbers
from contracts.agent import AgentStatus, RunContext
from contracts.analysis import AnalysisResult, ValidationCheck
from contracts.audit import read_events, verify_journal
from contracts.common import Period, load, save
from contracts.comparisons import (CheckKind, CheckStatus, ComparisonReport, FixMethod,
                                   UserDecision)
from contracts.llm import LLMUnavailable
from contracts.pipeline import context_for
from contracts.semantic import AnalysisRequest
from contracts.warehouse import TransformationReceipt, TransformationReceipts

REAL = context_for("comparisons", "run_001")
pytestmark = pytest.mark.skipif(
    not all(Path(REAL.inputs[k]).exists() for k in ("coverage", "warehouse", "manifest", "catalog")),
    reason="run `python -m auditor.dev.make_fake_inputs` and `python -m contracts.examples.install` first")


def request(cur, prev=None, dims=None) -> AnalysisRequest:
    return AnalysisRequest(question="test", metric="Revenue", dimensions=dims or [],
                           period=Period(start=cur[0], end=cur[1]),
                           compare_to=Period(start=prev[0], end=prev[1]) if prev else None)


def check(tmp_path: Path, req: AnalysisRequest, result=None, receipts=None):
    """Run the agent on real Olist data with a custom request. Returns (AgentResult, report, ctx)."""
    runs = tmp_path / "runs"
    inputs = dict(REAL.inputs)
    inputs["request"] = save(req, tmp_path / "request.json")
    inputs["result"] = save(result, tmp_path / "result.json") if result else tmp_path / "none.json"
    if receipts:
        inputs["receipts"] = save(receipts, tmp_path / "receipts.json")
    ctx = RunContext(run_id="test", agent="comparisons", inputs=inputs,
                     output_dir=runs / "test" / "comparisons", params={"llm": False},
                     journal=tmp_path / "journal.db")
    res = run(ctx)
    return res, load(ComparisonReport, res.outputs["report"]), ctx


def status_of(report, kind: CheckKind) -> CheckStatus:
    return next(c.status for c in report.checks if c.kind == kind)


AUG, JUL = ("2018-08-01", "2018-08-31"), ("2018-07-01", "2018-07-31")


# ---- the demo scenario --------------------------------------------------------------
def test_august_vs_july_is_blocked_and_fixed(tmp_path):
    res, rep, _ = check(tmp_path, request(AUG, JUL, ["customer_state"]))
    assert res.status == AgentStatus.NEEDS_REVIEW
    assert status_of(rep, CheckKind.COVERAGE) == CheckStatus.BLOCKING
    assert rep.checks[0].evidence["last_complete_day"] == "2018-08-23"

    fix = rep.proposed_fix
    assert fix.method == FixMethod.SAME_DAYS
    assert (fix.period.end, fix.compare_to.end) == ("2018-08-23", "2018-07-23")
    assert (fix.value_current, fix.value_previous) == (941291.36, 699238.79)
    assert fix.change_pct == pytest.approx(0.3462)

    alt = rep.alternatives[0]
    assert alt.method == FixMethod.PER_DAY_AVERAGE and alt.unit == "BRL/day"
    assert (alt.value_current, alt.value_previous) == (40925.71, 33158.19)


def test_real_population_difference_is_reported(tmp_path):
    """Roraima (RR) has delivered revenue in July 2018 but none in August."""
    _, rep, _ = check(tmp_path, request(AUG, JUL, ["customer_state"]))
    pop = next(c for c in rep.checks if c.kind == CheckKind.POPULATION)
    assert pop.status == CheckStatus.WARNING
    assert pop.evidence["customer_state_only_previous"] == ["RR"]


# ---- valid comparisons are left alone ----------------------------------------------------
@pytest.mark.parametrize("cur, prev", [
    (("2018-06-01", "2018-06-30"), ("2018-05-01", "2018-05-31")),   # 1 May holiday at an edge
    (("2017-11-01", "2017-11-30"), ("2017-10-01", "2017-10-31")),
])
def test_complete_months_pass(tmp_path, cur, prev):
    res, rep, _ = check(tmp_path, request(cur, prev))
    assert res.status == AgentStatus.SUCCESS
    assert all(c.status == CheckStatus.OK for c in rep.checks)
    assert rep.proposed_fix is None


def test_no_comparison_is_skipped(tmp_path):
    res, rep, _ = check(tmp_path, request(AUG))
    assert res.status == AgentStatus.SKIPPED and not rep.has_comparison


# ---- blocked without a fix --------------------------------------------------------------
@pytest.mark.parametrize("cur, prev", [
    (("2018-09-01", "2018-09-30"), AUG),                            # end of the data
    (("2016-10-01", "2016-10-31"), ("2017-10-01", "2017-10-31")),   # start of the data
])
def test_no_complete_day_means_no_fix(tmp_path, cur, prev):
    res, rep, _ = check(tmp_path, request(cur, prev))
    assert res.status == AgentStatus.NEEDS_REVIEW
    assert status_of(rep, CheckKind.COVERAGE) == CheckStatus.BLOCKING
    assert rep.proposed_fix is None and "should not be shown" in rep.summary


# ---- scale ------------------------------------------------------------------------------
def test_february_vs_january_warns_on_length(tmp_path):
    res, rep, _ = check(tmp_path, request(("2018-02-01", "2018-02-28"), ("2018-01-01", "2018-01-31")))
    assert status_of(rep, CheckKind.SCALE) == CheckStatus.WARNING
    assert res.status == AgentStatus.SUCCESS                  # a warning does not block
    assert rep.proposed_fix.method == FixMethod.PER_DAY_AVERAGE


def test_week_vs_month_is_blocked(tmp_path):
    res, rep, _ = check(tmp_path, request(("2018-05-01", "2018-05-07"), ("2018-04-01", "2018-04-30")))
    assert status_of(rep, CheckKind.SCALE) == CheckStatus.BLOCKING
    assert res.status == AgentStatus.NEEDS_REVIEW
    assert rep.proposed_fix.method == FixMethod.PER_DAY_AVERAGE


# ---- unit and grain ----------------------------------------------------------------------
def test_unit_mismatch_is_blocked(tmp_path):
    req = request(("2018-06-01", "2018-06-30"), ("2018-05-01", "2018-05-31"))
    result = AnalysisResult(request=req, kpi="Revenue@2.0", sql="-", rows=1, value_current=1.0,
                            unit="USD", validations=[ValidationCheck(name="x", passed=True, detail="-")])
    res, rep, _ = check(tmp_path, req, result=result)
    assert status_of(rep, CheckKind.UNIT) == CheckStatus.BLOCKING
    assert res.status == AgentStatus.NEEDS_REVIEW


def test_duplicating_join_is_blocked(tmp_path):
    receipts = TransformationReceipts(receipts=[TransformationReceipt(
        output_table="fact_payments", source_tables=["order_payments", "order_items"],
        join_keys=["order_id"], rows_before=103886, rows_after=117604, grain="payment")])
    res, rep, _ = check(tmp_path, request(("2018-06-01", "2018-06-30"), ("2018-05-01", "2018-05-31")),
                        receipts=receipts)
    assert status_of(rep, CheckKind.GRAIN) == CheckStatus.BLOCKING
    assert "duplicated rows" in next(c.message for c in rep.checks if c.kind == CheckKind.GRAIN)


# ---- journal and user decision ----------------------------------------------------------
def test_every_check_is_journaled(tmp_path):
    _, _, ctx = check(tmp_path, request(AUG, JUL))
    steps = [e.step for e in read_events(ctx.journal)]
    for kind in CheckKind:
        assert f"check_{kind.value}" in steps
    assert "propose_fix" in steps and "comparison_verdict" in steps
    assert verify_journal(ctx.journal).ok


def test_user_decision_is_recorded(tmp_path):
    _, _, ctx = check(tmp_path, request(AUG, JUL))
    kw = {"runs_root": tmp_path / "runs", "journal": ctx.journal}
    rep = record_decision("test", "accepted", "per_day_average", **kw)
    assert rep.user_decision == UserDecision.ACCEPTED and rep.chosen_fix == FixMethod.PER_DAY_AVERAGE
    with pytest.raises(ValueError):
        record_decision("test", "accepted", "convert_unit", **kw)    # never offered
    assert read_events(ctx.journal)[-1].step == "user_decision"


# ---- LLM summary: fact check ----------------------------------------------------------
class FakeLLM:
    def __init__(self, text=None, error=None):
        self.text, self.error = text, error

    def __call__(self, system, user, schema, **kw):
        if self.error:
            raise self.error
        return schema(summary=self.text)


TEMPLATE = ("August 2018-08-01..2018-08-31 = 985,414.28 BRL (-4.1%). "
            "Recommended: days 1 to 23, 941,291.36 (+34.6%).")


def test_faithful_llm_text_is_accepted():
    text = "Attention : 985,414.28 BRL (-4.1%) est trompeur ; avec les jours 1 à 23 : 941,291.36 (+34.6%)."
    summary, source = summarize(TEMPLATE, [], [], llm=FakeLLM(text))
    assert summary == text and source.startswith("llm:")


def test_llm_text_with_invented_number_is_rejected():
    text = "Revenue grew by 12.5% thanks to the summer sales."      # 12.5 is invented
    summary, source = summarize(TEMPLATE, [], [], llm=FakeLLM(text))
    assert summary == TEMPLATE and source == "template"
    assert unsupported_numbers(text, allowed_numbers(TEMPLATE)) == ["12.5"]


def test_llm_text_hiding_an_option_is_rejected():
    """Completeness: an alternative the manager could choose must not disappear."""
    from contracts.comparisons import ProposedFix
    p = Period(start="2018-08-01", end="2018-08-23")
    rec = ProposedFix(method=FixMethod.SAME_DAYS, description="d", justification="j", period=p,
                      compare_to=p, value_current=941291.36, value_previous=699238.79)
    alt = ProposedFix(method=FixMethod.PER_DAY_AVERAGE, description="d", justification="j", period=p,
                      compare_to=p, value_current=40925.71, value_previous=33158.19)
    facts = TEMPLATE + " 699,238.79 40,925.71 33,158.19"
    only_rec = "Use days 1 to 23: 941,291.36 against 699,238.79 (+34.6%)."
    summary, source = summarize(facts, [], [rec, alt], llm=FakeLLM(only_rec))
    assert source == "template"
    both = only_rec + " Or per day: 40,925.71 against 33,158.19."
    assert summarize(facts, [], [rec, alt], llm=FakeLLM(both))[1].startswith("llm:")


def test_no_ollama_falls_back_to_template():
    summary, source = summarize(TEMPLATE, [], [], llm=FakeLLM(error=LLMUnavailable("down")))
    assert (summary, source) == (TEMPLATE, "template")
