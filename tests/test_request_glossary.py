"""tests/test_request_glossary.py — the request agent follows the glossary, the catalog and the contract.

Uses the real catalog (kpi/catalog.yaml) and glossary (semantic/glossary.yaml), then the
Analyst on the request the agent wrote, as the orchestrator chains them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import contracts.llm as llm
from contracts import AgentStatus, context_for, read_events
from contracts.common import save
from contracts.intake import Upload
from contracts.registry import read_output
from contracts.semantic import AnalysisRequest, Glossary, KpiCatalog, load_yaml
from semantic.request import (_find_dimensions, _find_filters, _find_metric, _find_period,
                              _find_top_n, _match_terms, run)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "contracts/examples/run_001/request/analysis_request.json"


@pytest.fixture(scope="module")
def catalog() -> KpiCatalog:
    return load_yaml(KpiCatalog, REPO_ROOT / "kpi/catalog.yaml")


@pytest.fixture(scope="module")
def glossary() -> Glossary:
    return load_yaml(Glossary, REPO_ROOT / "semantic/glossary.yaml")


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """The Analyst's insight sentences fall back to their deterministic text: no Groq call."""
    def down(*args, **kwargs):
        raise llm.LLMUnavailable("LLM disabled in this test")
    monkeypatch.setattr(llm, "_post", down)


def ask(question: str, run_id: str, root: Path):
    """Write the upload, run the request agent exactly as the orchestrator does."""
    save(Upload(question=question, tables={}), root / run_id / "upload" / "upload.json")
    return run(context_for("request", run_id, runs_root=root, journal=root / "journal.db"))


# ── The contract example ──────────────────────────────────────────────────────

def test_contract_example_is_reproduced(tmp_path):
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    out = ask(example["question"], "ex", tmp_path)

    assert out.status == AgentStatus.SUCCESS
    request = read_output(out.outputs["request"], "request.request")   # valid against the contract
    assert request.metric == example["metric"]
    assert request.dimensions == example["dimensions"]
    assert request.period.model_dump() == example["period"]
    assert request.compare_to.model_dump() == example["compare_to"]
    assert request.matched_terms == example["matched_terms"]


# ── Bug 1: periods ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "Revenue in August 2018 compared with July 2018",
    "Revenue in August 2018 compared to July 2018",
    "Revenue in August vs July 2018",
    "Compared with July, how was revenue in August 2018?",
    "Chiffre d'affaires en août 2018 par rapport à juillet 2018",
    "CA de aout 2018 comparé à juillet 2018",
    "Ventes août 2018 contre juillet 2018",
])
def test_main_month_is_the_one_asked_about(question):
    period, compare = _find_period(question)
    assert (period.start, period.end) == ("2018-08-01", "2018-08-31")
    assert (compare.start, compare.end) == ("2018-07-01", "2018-07-31")


def test_french_months():
    period, _ = _find_period("Commandes en février 2018")
    assert (period.start, period.end) == ("2018-02-01", "2018-02-28")
    period, _ = _find_period("ventes de décembre 2017")
    assert period.start == "2017-12-01"


def test_each_month_keeps_its_own_year():
    period, compare = _find_period("Sales in January 2018 vs December 2017")
    assert period.start == "2018-01-01"
    assert compare.start == "2017-12-01"


def test_a_year_alone_is_the_whole_year():
    period, compare = _find_period("Revenue by month in 2017")
    assert (period.start, period.end) == ("2017-01-01", "2017-12-31")
    assert compare is None


# ── Bug 2: dimensions the KPI does not allow ──────────────────────────────────

def test_state_alone_is_the_customer_state(catalog, glossary):
    assert _find_dimensions("Revenue by state in August 2018", catalog, glossary) == ["customer_state"]


def test_seller_state_is_found_when_asked(catalog, glossary):
    q = "Number of orders by seller state in May 2018"
    assert _find_metric(q, catalog, glossary)[0] == "Orders"
    assert _find_dimensions(q, catalog, glossary) == ["seller_state"]


def test_dimension_not_allowed_needs_review(tmp_path):
    out = ask("Revenue by seller state in May 2018", "na", tmp_path)
    assert out.status == AgentStatus.NEEDS_REVIEW
    assert "seller_state" in out.message
    assert not (tmp_path / "na/request/analysis_request.json").exists()
    events = read_events(tmp_path / "journal.db")
    assert events[-1].evidence["reason"] == "dimension or filter not allowed for this KPI"


# ── Bug 3: glossary synonyms, whole words ─────────────────────────────────────

@pytest.mark.parametrize("question, metric, dimensions", [
    ("Chiffre d'affaires par région en mai 2018", "Revenue", ["customer_state"]),
    ("Le CA par mode de paiement en mai 2018", "Revenue", ["payment_type"]),
    ("Panier moyen par catégorie en mai 2018", "AverageBasket", ["product_category"]),
    ("Average order value by payment method, May 2018", "AverageBasket", ["payment_type"]),
    ("Nombre de clients par état en mai 2018", "Customers", ["customer_state"]),
    ("Frais de port par catégorie de produit en mai 2018", "Freight", ["product_category"]),
    ("Units sold by category in May 2018", "ItemsSold", ["product_category"]),
    ("Sales per order in May 2018", "Revenue", []),              # "order" is not order_month
    ("Nombre de commandes du mois de mai 2018", "Orders", []),   # "mois de mai" is the period
    ("Revenue by month in 2018", "Revenue", ["order_month"]),
])
def test_glossary_synonyms(question, metric, dimensions, catalog, glossary):
    assert _find_metric(question, catalog, glossary)[0] == metric
    assert _find_dimensions(question, catalog, glossary) == dimensions


def test_french_ca_is_not_ca(catalog, glossary):
    """'ça' (that) is not 'CA' (chiffre d'affaires), even in lower case."""
    assert _find_metric("ça a baissé en mars ?", catalog, glossary)[0] is None
    assert _find_metric("ca en aout", catalog, glossary)[0] == "Revenue"


# ── Filters: only WHERE parts the Analyst accepts (contract AnalysisRequest.filters) ──

def test_top_n_is_not_a_filter(catalog):
    q = "top 5 categories by orders in august"
    assert _find_filters(q, catalog) == []
    assert _find_top_n(q) == 5


def test_two_letter_words_are_not_state_codes(catalog):
    assert _find_filters("revenue hors de saison en aout", catalog) == []
    assert _find_filters("revenue en aout sauf sp", catalog) == ["customer_state != 'SP'"]


def test_exclusion_adds_its_dimension(tmp_path):
    """The Analyst filters only on a dimension of the breakdown: customer_state is added."""
    out = ask("Revenue by payment method in August 2018 excluding SP", "ex_sp", tmp_path)
    assert out.status == AgentStatus.SUCCESS
    request = read_output(out.outputs["request"], "request.request")
    assert request.dimensions == ["payment_type", "customer_state"]
    assert request.filters == ["customer_state != 'SP'"]


def test_redundant_status_filter_is_dropped(tmp_path):
    """'excluding canceled' adds nothing: every KPI already keeps delivered orders only."""
    out = ask("Revenue by state in August 2018 excluding canceled", "ex_cancel", tmp_path)
    request = read_output(out.outputs["request"], "request.request")
    assert request.filters == []


def test_impossible_day_range_needs_review(tmp_path):
    out = ask("Chiffre d'affaires du 5 au 31 juin 2018", "bad_day", tmp_path)
    assert out.status == AgentStatus.NEEDS_REVIEW


def test_matched_terms_keep_the_words_of_the_question(catalog, glossary):
    terms = _match_terms("Chiffre d'affaires par région en août 2018", glossary, catalog)
    assert terms == {"Chiffre d'affaires": "Revenue", "région": "customer_state"}


# ── From the question to the Analyst ──────────────────────────────────────────

def test_french_question_gives_the_analyst_result(tmp_path):
    from analysis.analyst import run as analyse
    from analysis.dev_warehouse import EXPECTED, build

    build("fr", tmp_path)
    out = ask("Chiffre d'affaires par région en août 2018 par rapport à juillet 2018", "fr", tmp_path)
    assert out.status == AgentStatus.SUCCESS
    request = read_output(out.outputs["request"], "request.request")
    assert isinstance(request, AnalysisRequest)
    assert (request.metric, request.dimensions) == ("Revenue", ["customer_state"])
    assert (request.period.start, request.compare_to.start) == ("2018-08-01", "2018-07-01")

    result = analyse(context_for("analysis", "fr", runs_root=tmp_path, journal=tmp_path / "journal.db"))
    assert result.status == AgentStatus.SUCCESS
    analysis = read_output(result.outputs["result"], "analysis.result")
    assert analysis.value_current == EXPECTED["2018-08"]["total"]
    assert analysis.value_previous == EXPECTED["2018-07"]["total"]


def test_exclusion_filter_is_accepted_by_the_analyst(tmp_path):
    from analysis.analyst import run as analyse
    from analysis.dev_warehouse import build

    build("sp", tmp_path)
    out = ask("Revenue by state in August 2018 vs July 2018 sauf SP", "sp", tmp_path)
    assert out.status == AgentStatus.SUCCESS
    result = analyse(context_for("analysis", "sp", runs_root=tmp_path, journal=tmp_path / "journal.db"))
    assert result.status == AgentStatus.SUCCESS, result.message
