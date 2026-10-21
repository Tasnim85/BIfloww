"""Shared test setup."""
import os

# Charts are drawn in memory only: on Windows the default Tk backend crashes when a chart
# is drawn outside the main thread (Streamlit's test runner does that).
os.environ.setdefault("MPLBACKEND", "Agg")
