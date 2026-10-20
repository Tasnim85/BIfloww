"""The Streamlit screens open without error (headless, with streamlit.testing).
python -m pytest tests/test_ui.py -v

Read-only: no button is clicked here, so the demo journal and reports are not changed.
(The buttons were tested by hand; the tampering demo only touches a copy.)
"""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

READY = Path("runs/demo_journal.db").exists() and Path("runs/run_001/comparisons/comparison_report.json").exists()
pytestmark = pytest.mark.skipif(not READY, reason="run make_fake_inputs and seed_demo_journal first")

PAGES = ["run_view", "home", "comparisons_page", "explanations_page", "why_page", "journal_page", "drift_page"]


def script(body: str, lang: str = "en") -> AppTest:
    at = AppTest.from_string("import sys; sys.path.insert(0, '.')\n" + body, default_timeout=180)
    at.session_state["lang"] = lang
    return at


def texts(at: AppTest) -> list[str]:
    """Every text the user sees on the page (titles, captions, messages, buttons, labels)."""
    out = []
    for kind in ("title", "subheader", "caption", "markdown", "info", "success", "warning", "error"):
        out += [str(e.value) for e in getattr(at, kind)]
    out += [e.label for e in at.button] + [e.label for e in at.expander] + [e.label for e in at.selectbox]
    out += [e.label for e in at.radio] + [e.label for e in at.checkbox]
    return out


@pytest.mark.parametrize("lang", ["en", "fr"])
@pytest.mark.parametrize("page", PAGES)
def test_page_opens(page, lang):
    at = script(f"from auditor.ui import {page}\n{page}.render()", lang).run()
    assert not at.exception, at.exception[0].value


FRENCH = ("é", "è", "à ", "ç", " le ", " la ", " les ", " des ", " du ", "Aucun", "Lance ")


@pytest.mark.parametrize("page", PAGES)
def test_english_mode_shows_no_french(page):
    """The demo is in English: no French word may remain on any page."""
    at = script(f"from auditor.ui import {page}\n{page}.render()", "en").run()
    bad = [x for x in texts(at) if any(w in x for w in FRENCH)]
    assert not bad, bad


@pytest.mark.parametrize("component", [
    "trust_badge('run_001', DEMO_JOURNAL)",
    "comparison_banner('run_001', DEMO_JOURNAL)",
    "audit_panel('run_001', DEMO_JOURNAL)",
    "why_box('run_001', DEMO_JOURNAL, ['Pourquoi ?'])",
])
def test_component_draws_alone(component):
    """Each block works on its own: this is how Samar places it in the result screen."""
    at = script("from auditor.ui.components import *\nfrom auditor.ui.data import DEMO_JOURNAL\n"
                + component).run()
    assert not at.exception, at.exception[0].value


def test_result_screen_shows_the_auditor_blocks():
    at = script("from auditor.ui import run_view\nrun_view.render()").run()            # English by default
    labels = [e.label for e in at.expander]
    assert any("Audit of this run" in label for label in labels)
    assert any("Journal" in m.value for m in at.markdown)          # trust badge


def test_trust_badge_follows_the_language():
    """The badge reported by Tasnim: it stayed in French whatever the language."""
    en = script("from auditor.ui.components import *\nfrom auditor.ui.data import DEMO_JOURNAL\n"
                "trust_badge('run_001', DEMO_JOURNAL)", "en").run()
    fr = script("from auditor.ui.components import *\nfrom auditor.ui.data import DEMO_JOURNAL\n"
                "trust_badge('run_001', DEMO_JOURNAL)", "fr").run()
    en_text, fr_text = " ".join(texts(en)), " ".join(texts(fr))
    assert "decisions" in en_text and "Drift" in en_text and "décisions" not in en_text
    assert "décisions" in fr_text
