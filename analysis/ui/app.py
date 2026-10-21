"""Standalone app of Rabeb's part. From the repo root:

    streamlit run analysis/ui/app.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root, so `contracts`, `analysis` import
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from analysis.ui import PAGES  # noqa: E402
from analysis.ui.texts import t  # noqa: E402

st.set_page_config(page_title="BIFlow · Analyst", page_icon="📊", layout="wide")
if "lang" not in st.session_state:
    st.session_state["lang"] = "en"
st.sidebar.radio(t("lang_label"), ["en", "fr"], key="lang", horizontal=True,
                 format_func={"en": "🇬🇧 English", "fr": "🇫🇷 Français"}.get)
st.navigation([st.Page(fn, title=t(f"pages.{title}"), icon=icon, url_path=path)
               for fn, title, icon, path in PAGES]).run()
