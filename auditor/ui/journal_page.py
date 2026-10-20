"""Audit journal page: read, verify, and the tampering demo (on a COPY only)."""
import shutil
import sqlite3

import pandas as pd
import streamlit as st

from auditor.ui.data import TAMPER_COPY, pick_journal
from contracts.audit import last_hash, read_events, verify_journal


def render() -> None:
    st.title("Journal d'audit")
    st.caption("Chaque agent écrit ses décisions. En ajout seul, chaîné par SHA-256 : "
               "toute modification est détectable.")

    journal = pick_journal(key="journal_page")
    if journal is None:
        return
    events = read_events(journal)
    if not events:
        st.info("Journal vide.")
        return

    c1, c2 = st.columns(2)
    run = c1.selectbox("Run", ["(tous)"] + sorted({e.run_id for e in events}))
    agent = c2.selectbox("Agent", ["(tous)"] + sorted({e.agent for e in events}))
    hide_llm = st.checkbox("Masquer les appels au LLM", value=True)
    rows = [e for e in events if (run == "(tous)" or e.run_id == run)
            and (agent == "(tous)" or e.agent == agent) and not (hide_llm and e.step.startswith("llm:"))]
    st.dataframe(pd.DataFrame([{
        "#": e.entry_id, "run": e.run_id, "agent": e.agent, "étape": e.step, "décision": e.decision,
        "règle": e.rule_version, "quand": e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "hash": e.entry_hash[:10], "hash précédent": e.prev_hash[:10]} for e in rows]),
        hide_index=True, width="stretch")

    picked = st.number_input("Voir les preuves de l'entrée #", min_value=1,
                             max_value=max(e.entry_id for e in events), value=rows[0].entry_id if rows else 1)
    entry = next((e for e in events if e.entry_id == picked), None)
    if entry:
        st.json(entry.evidence, expanded=False)

    st.subheader("Intégrité")
    if st.button("Vérifier la chaîne", type="primary"):
        st.session_state["integrity"] = verify_journal(journal)
    rep = st.session_state.get("integrity")
    if rep:
        (st.success if rep.ok else st.error)(f"{rep.problem} ({rep.entries_checked} entrées vérifiées)")
    st.write("**Ancre (dernier hash) :**")
    st.code(last_hash(journal))
    st.caption("En production, cette ancre serait conservée ailleurs (signature, stockage en écriture "
               "unique) : même une chaîne entièrement recalculée serait alors détectée.")

    st.subheader("Démonstration de falsification")
    st.write("Simule un attaquant qui a accès au fichier : il supprime la protection, puis modifie "
             "une entrée. **La démo travaille sur une copie**, jamais sur le journal choisi.")
    c1, c2, c3 = st.columns(3)
    if c1.button("1. Créer la copie"):
        shutil.copyfile(journal, TAMPER_COPY)
        st.session_state.pop("tamper_report", None)
    target = c2.number_input("2. Entrée à falsifier", min_value=1, max_value=len(events), value=min(5, len(events)))
    if c2.button("Falsifier", disabled=not TAMPER_COPY.exists()):
        con = sqlite3.connect(TAMPER_COPY)
        con.execute("DROP TRIGGER IF EXISTS journal_no_update")
        con.execute("UPDATE journal SET decision = 'HACKED' WHERE entry_id = ?", (int(target),))
        con.commit()
        con.close()
        st.session_state["tampered"] = int(target)
    if c3.button("3. Vérifier la copie", disabled=not TAMPER_COPY.exists()):
        st.session_state["tamper_report"] = verify_journal(TAMPER_COPY)
    if "tampered" in st.session_state:
        st.warning(f"L'entrée #{st.session_state['tampered']} de la copie a été modifiée directement.")
    t = st.session_state.get("tamper_report")
    if t:
        (st.success if t.ok else st.error)(("Falsification détectée : " if not t.ok else "") + t.problem)
