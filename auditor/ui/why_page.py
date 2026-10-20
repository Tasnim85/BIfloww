"""The "why?" agent page: the why_box component on any run of any journal."""
import streamlit as st

from auditor.ui.components import why_box
from auditor.ui.data import pick_journal, runs_in

SUGGESTIONS = {
    "run_001": ["Pourquoi la comparaison août/juillet a-t-elle été bloquée ?",
                "D'où vient le chiffre d'affaires ?",
                "Pourquoi le paiement le plus anormal a-t-il été signalé ?"],
    "drift": ["Pourquoi ce run a-t-il été signalé ?",
              "Les données d'entrée ont-elles changé dans ce run ?"],
}


def render() -> None:
    st.title("Demander « pourquoi ? »")
    st.caption("Question → l'enquêteur appelle des outils en lecture seule → le rédacteur répond → "
               "le contrôle vérifie chaque chiffre et chaque citation")
    c1, c2 = st.columns(2)
    with c1:
        journal = pick_journal(key="why_journal", prefer="Démo run_001")
    if journal is None:
        return
    with c2:
        run_id = st.selectbox("Run", runs_in(journal), key="why_run")
    why_box(run_id, journal, SUGGESTIONS["run_001"] if run_id == "run_001" else SUGGESTIONS["drift"],
            key=f"whypage_{run_id}")
