"""Tasnim's Streamlit pages (BO3 Auditor + BO4-12 comparisons).

Two levels (see auditor/ui/README.md):
  - auditor.ui.components: BLOCKS to put inside the pipeline's result screen
    (trust_badge, comparison_banner, audit_panel, why_box) - the main integration;
  - PAGES: detailed pages, each a function render(), for exploring and the demo.

Standalone, to show this part alone:   streamlit run auditor/ui/app.py
"""
import matplotlib

# Draw in memory only ("Agg"). On Windows the default Tk backend crashes when charts are
# drawn outside the main thread (Streamlit, tests): "Windows fatal exception 0x80000003".
matplotlib.use("Agg")

from auditor.ui import (comparisons_page, drift_page, explanations_page, home,  # noqa: E402
                        journal_page, run_view, why_page)

PAGES = [  # (render function, title key in i18n "ui.pages.*", icon, url path)
    (run_view.render, "run", "🧾", "run_result"),
    (home.render, "home", "🏠", "auditor_home"),
    (comparisons_page.render, "comparisons", "⚖️", "comparisons"),
    (explanations_page.render, "explanations", "🔍", "explanations"),
    (why_page.render, "why", "💬", "why"),
    (journal_page.render, "journal", "📜", "journal"),
    (drift_page.render, "drift", "📈", "drift"),
]
