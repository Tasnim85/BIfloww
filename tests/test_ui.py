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


def script(body: str) -> AppTest:
    return AppTest.from_string("import sys; sys.path.insert(0, '.')\n" + body, default_timeout=180)


@pytest.mark.parametrize("page", PAGES)
def test_page_opens(page):
    at = script(f"from auditor.ui import {page}\n{page}.render()").run()
    assert not at.exception, at.exception[0].value


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
    at = script("from auditor.ui import run_view\nrun_view.render()").run()
    labels = [e.label for e in at.expander]
    assert any("Audit de ce run" in label for label in labels)
    assert any("Journal" in m.value for m in at.markdown)          # trust badge
