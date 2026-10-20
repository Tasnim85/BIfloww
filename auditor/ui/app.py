"""Standalone app of Tasnim's part. From the repo root:

    streamlit run auditor/ui/app.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root, so `contracts`, `auditor`... import
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from auditor.ui import PAGES  # noqa: E402
from auditor.ui.data import UI_DEFAULT_LANG, t  # noqa: E402

st.set_page_config(page_title="BIFlow · Auditor", page_icon="🛡️", layout="wide")
if "lang" not in st.session_state:
    st.session_state["lang"] = UI_DEFAULT_LANG
st.sidebar.radio(t("lang_label"), ["en", "fr"], key="lang", horizontal=True,
                 format_func={"en": "🇬🇧 English", "fr": "🇫🇷 Français"}.get, help=t("lang_help"))
st.navigation([st.Page(fn, title=t(f"pages.{title}"), icon=icon, url_path=path)
               for fn, title, icon, path in PAGES]).run()
