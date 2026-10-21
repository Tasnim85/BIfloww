"""Rabeb's Streamlit pages (step 5: the Analyst, the KPI catalog, the KPI proposer).

Two levels, like Tasnim's auditor/ui (see analysis/ui/README.md):
  - analysis.ui.components: BLOCKS for the pipeline's result screen (Samar's app);
  - PAGES: detailed pages, each a function render(), for exploring and the demo.

Standalone:   streamlit run analysis/ui/app.py
"""
import matplotlib

# Draw in memory only: on Windows the default Tk backend crashes outside the main thread.
matplotlib.use("Agg")

from analysis.ui import catalog_page, proposer_page, run_view  # noqa: E402

PAGES = [  # (render function, title key in texts.py "pages.*", icon, url path)
    (run_view.render, "run", "📊", "analysis_result"),
    (catalog_page.render, "catalog", "📚", "kpi_catalog"),
    (proposer_page.render, "proposer", "🧪", "kpi_proposer"),
]
