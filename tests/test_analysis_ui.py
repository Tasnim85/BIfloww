"""Rabeb's Streamlit screens open without error, in English and French (headless).
python -m pytest tests/test_analysis_ui.py -v

Everything happens in a temporary folder: a mini warehouse is built there and the Analyst
is run once (LLM switched off), so the real runs/ folder and journal are not touched."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import contracts.llm as llm  # noqa: E402
from analysis.analyst import run  # noqa: E402
from analysis.dev_warehouse import build  # noqa: E402
from contracts.pipeline import context_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["run_view", "catalog_page", "proposer_page"]
FRENCH = ("é", "è", "à ", "ç", " le ", " la ", " les ", " des ", " du ", "Aucun")


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # runs/ and the journal live in tmp_path

    def down(*a, **k):
        raise llm.LLMUnavailable("LLM disabled in this test")
    monkeypatch.setattr(llm, "_post", down)
    build("dev_001")
    run(context_for("analysis", "dev_001"))


def script(body: str, lang: str = "en") -> AppTest:
    at = AppTest.from_string(f"import sys; sys.path.insert(0, {str(ROOT)!r})\n" + body, default_timeout=120)
    at.session_state["lang"] = lang
    return at


def texts(at: AppTest) -> list[str]:
    out = []
    for kind in ("title", "subheader", "caption", "markdown", "info", "success", "warning", "error"):
        out += [str(e.value) for e in getattr(at, kind)]
    return out + [e.label for e in at.button] + [e.label for e in at.expander] + [e.label for e in at.selectbox]


@pytest.mark.parametrize("lang", ["en", "fr"])
@pytest.mark.parametrize("page", PAGES)
def test_page_opens(page, lang):
    at = script(f"from analysis.ui import {page}\n{page}.render()", lang).run()
    assert not at.exception, at.exception[0].value


@pytest.mark.parametrize("page", PAGES)
def test_english_mode_shows_no_french(page):
    at = script(f"from analysis.ui import {page}\n{page}.render()", "en").run()
    bad = [x for x in texts(at) if any(w in x for w in FRENCH)]
    assert not bad, bad


@pytest.mark.parametrize("block", ["kpi_header", "insights_box", "validation_panel", "sql_box"])
def test_block_draws_alone(block):
    """How Samar places a block in the result screen."""
    at = script(f"from analysis.ui.components import {block}\n{block}('dev_001')").run()
    assert not at.exception, at.exception[0].value


def test_result_page_shows_the_validated_number():
    at = script("from analysis.ui import run_view\nrun_view.render()").run()
    assert any("400.00 BRL" in m.value for m in at.metric)                 # August revenue
    assert any("Validated" in str(s.value) for s in at.success)
    assert len([e for e in at.expander if e.label.startswith("✅")]) == 4    # the 4 BO3-03 checks


def test_catalog_page_computes_a_kpi_with_its_checks():
    at = script("from analysis.ui import catalog_page\ncatalog_page.render()").run()
    at.button(key="cat_go").click().run()
    assert not at.exception
    assert sum("✅" in m.value for m in at.markdown) == 4


def test_proposer_page_proposes_without_llm():
    at = script("from analysis.ui import proposer_page\nproposer_page.render()").run()
    at.checkbox[0].uncheck()
    at.button[0].click().run()
    assert not at.exception, at.exception and at.exception[0].value
    assert any("mechanical" in str(s.value) for s in at.success)
