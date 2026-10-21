"""Multilingual texts (French / English): python -m pytest tests/test_i18n.py -v

English stays the canonical language (contracts, journal); every text the user sees can be
rendered in French or English at display time, numbers formatted by code (never by an LLM).
"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.ensemble import IsolationForest

from api.main import create_app
from auditor.agent import run as run_auditor
from auditor.dev import clinics
from auditor.drift.monitor import monitor_runs
from auditor.why import WhyAgent
from comparisons.checker import run as run_checker
from contracts.common import load
from contracts.comparisons import ComparisonReport
from contracts.i18n import (Msg, check_catalogs, detect_language, fmt, from_accept_language, lang_code,
                            localize, render)
from contracts.llm import LLMUnavailable
from contracts.pipeline import context_for, output_path
from contracts.xai import ExplanationReport

RUN = "clinic_001"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("i18n")
    runs = root / "runs"
    clinics.write_run(root, RUN, clinics.visits())
    kw = {"runs_root": runs, "repo_root": root, "journal": runs / "clinics_journal.db"}
    res = run_checker(context_for("comparisons", RUN, params={"llm": False}, **kw))
    run_auditor(context_for("auditor", RUN, params={"n_normal": 5}, **kw))
    return root, runs, load(ComparisonReport, res.outputs["report"])


# ---- the catalogs and the formatting ------------------------------------------------------
def test_catalogs_have_the_same_keys_and_placeholders():
    assert check_catalogs() == []


def test_numbers_are_formatted_by_code_in_each_language():
    assert fmt(941291.36, "num2", "en") == "941,291.36"
    assert fmt(941291.36, "num2", "fr") == "941 291,36"
    assert fmt(0.3462, "spct", "en") == "+34.6%" and fmt(0.3462, "spct", "fr") == "+34,6 %"
    assert fmt(2647.76, "auto", "fr") == "2 647,76" and fmt(100.0, "auto", "en") == "100"
    assert fmt(None, "num2", "fr") == "n.d."


def test_language_detection_and_codes():
    assert detect_language("Pourquoi la comparaison a-t-elle été bloquée ?") == "fr"
    assert detect_language("Why was the comparison blocked?") == "en"
    assert detect_language("D'où vient le chiffre d'affaires ?") == "fr"
    assert detect_language("Where does revenue come from?") == "en"
    assert [lang_code(x) for x in ("French", "fr-FR", "English", "en", None)] == ["fr", "fr", "en", "en", "fr"]
    assert from_accept_language("en-GB,en;q=0.9,fr;q=0.8") == "en" and from_accept_language("de-DE") is None


def test_unknown_key_is_an_error_not_a_silent_blank():
    with pytest.raises(KeyError):
        render(Msg(key="nope.nothing"), "fr")


# ---- BO4-12 ------------------------------------------------------------------------------------
def test_english_stays_the_stored_text(world):
    rep = world[2]
    for c in rep.checks:
        assert c.message == render(c.message_parts, "en")
    assert rep.summary == render(rep.summary_parts, "en") and rep.summary_lang is None
    assert localize(rep, "en") == rep


def test_comparison_report_in_french(world):
    fr = localize(world[2], "fr")
    cov = next(c for c in fr.checks if c.kind.value == "coverage")
    assert cov.message.startswith("La période étudiée (2024-03-01 au 2024-03-31) n'est complète que du "
                                  "2024-03-01 au 2024-03-13")
    pop = next(c for c in fr.checks if c.kind.value == "population")
    assert "uniquement dans la période étudiée : Gabes" in pop.message
    assert fr.summary.startswith("Attention : cette comparaison est trompeuse telle que demandée")
    assert fr.proposed_fix.description.startswith("Comparer les jours 1 à 13")
    assert fr.alternatives[0].unit == "TND/jour"
    assert "Rien n'est modifié tant que vous n'avez pas choisi." in fr.summary
    assert fr.checks[0].evidence == world[2].checks[0].evidence          # the numbers never change


def test_an_llm_summary_is_kept_only_in_its_own_language(world):
    llm = world[2].model_copy(update={"summary": "Texte du LLM.", "summary_source": "llm:m", "summary_lang": "fr"})
    assert localize(llm, "fr").summary == "Texte du LLM."
    en = localize(llm, "en")
    assert en.summary.startswith("Careful: this comparison is misleading") and en.summary_source == "template"


# ---- SHAP, drift, why? --------------------------------------------------------------------------
def test_shap_sentences_in_french(world):
    _, runs, _ = world
    rep = load(ExplanationReport, output_path(RUN, "auditor", "explanations", runs))
    first = next(e for e in rep.explanations if e.is_anomaly)
    fr = localize(first, "fr")
    assert fr.narrative.startswith("Signalée comme anomalie car ")
    assert "la valeur typique de" in fr.narrative and "coupes" in fr.narrative
    assert first.narrative.startswith("Flagged as anomalous because ")


def test_drift_diagnosis_in_french(tmp_path):
    df = clinics.visits()
    df["month"] = pd.to_datetime(df["visit_date"]).dt.strftime("%Y-%m")
    ref = ["2023-10", "2023-11", "2023-12", "2024-01"]
    model = IsolationForest(n_estimators=50, contamination=0.01, random_state=0).fit(
        df[df["month"].isin(ref)][clinics.FEATURES])
    for m in ref:
        clinics.write_run(tmp_path, f"m_{m}", df[df["month"] == m].reset_index(drop=True), model=model)
    up = df[df["month"] == "2024-02"].reset_index(drop=True).copy()
    up["fee_tnd"] *= 1.6
    clinics.write_run(tmp_path, "up", up, model=model)
    rep = monitor_runs([f"m_{m}" for m in ref], ["up"], runs_root=tmp_path / "runs", journal=tmp_path / "j.db")["up"]
    fr = localize(rep, "fr").narrative
    assert "les données d'entrée ont changé" in fr and fr.endswith("C'est un diagnostic, pas une preuve : un humain décide.")
    assert rep.narrative.endswith("This is a diagnosis, not a proof: a human decides.")


def test_why_answers_in_the_language_of_the_question(world):
    root, runs, _ = world

    def down(*a, **k):
        raise LLMUnavailable("no key")
    agent = WhyAgent(RUN, journal=runs / "clinics_journal.db", runs_root=runs, repo_root=root, llm=down, writer=down)
    fr = agent.ask("Pourquoi la comparaison a-t-elle été bloquée ?")
    en = agent.ask("Why was the comparison blocked?")
    assert fr.lang == "fr" and fr.answer.startswith("Réponse automatique")
    assert en.lang == "en" and en.answer.startswith("Automatic answer")


# ---- API ----------------------------------------------------------------------------------------
def test_api_language_choice(world):
    root, runs, _ = world
    c = TestClient(create_app(runs_root=runs, repo_root=root))
    default = c.get(f"/api/runs/{RUN}/comparison").json()
    assert default["summary"].startswith("Attention")                                # French by default
    assert c.get(f"/api/runs/{RUN}/comparison", params={"lang": "en"}).json()["summary"].startswith("Careful")
    h = c.get(f"/api/runs/{RUN}/comparison", headers={"Accept-Language": "en-US,en;q=0.9"}).json()
    assert h["summary"].startswith("Careful")
    assert c.get(f"/api/runs/{RUN}/comparison", params={"lang": "de"}).status_code == 422
    s = c.get(f"/api/runs/{RUN}", params={"lang": "en"}).json()
    assert s["comparison"]["checks"][0]["message"].startswith("The current period")
    e = c.get(f"/api/runs/{RUN}/explanations", params={"limit": 1}).json()["items"][0]
    assert e["narrative"].startswith("Signalée comme anomalie")
    assert c.get(f"/api/runs/{RUN}/drift").json()["narrative"].startswith("La surveillance du drift")
