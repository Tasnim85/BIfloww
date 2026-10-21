"""Audit journal page: read, verify, and the tampering demo (on a COPY only)."""
import shutil
import sqlite3

import pandas as pd
import streamlit as st

from auditor.ui.data import TAMPER_COPY, pick_journal, t
from contracts.audit import last_hash, read_events, verify_journal


def render() -> None:
    st.title(t("jr.title"))
    st.caption(t("jr.caption"))

    journal = pick_journal(key="journal_page")
    if journal is None:
        return
    events = read_events(journal)
    if not events:
        st.info(t("jr.empty"))
        return

    c1, c2 = st.columns(2)
    ALL = t("common.all")
    run = c1.selectbox(t("common.run"), [ALL] + sorted({e.run_id for e in events}))
    agent = c2.selectbox(t("jr.agent"), [ALL] + sorted({e.agent for e in events}))
    hide_llm = st.checkbox(t("jr.hide_llm"), value=True)
    rows = [e for e in events if (run == ALL or e.run_id == run)
            and (agent == ALL or e.agent == agent) and not (hide_llm and e.step.startswith("llm:"))]
    st.dataframe(pd.DataFrame([{
        "#": e.entry_id, "run": e.run_id, "agent": e.agent, t("jr.step"): e.step, t("jr.decision"): e.decision,
        t("jr.rule"): e.rule_version, t("jr.when"): e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "hash": e.entry_hash[:10], t("jr.prev_hash"): e.prev_hash[:10]} for e in rows]),
        hide_index=True, width="stretch")

    picked = st.number_input(t("jr.see"), min_value=1,
                             max_value=max(e.entry_id for e in events), value=rows[0].entry_id if rows else 1)
    entry = next((e for e in events if e.entry_id == picked), None)
    if entry:
        st.json(entry.evidence, expanded=False)

    st.subheader(t("jr.integrity"))
    if st.button(t("jr.verify"), type="primary"):
        st.session_state["integrity"] = verify_journal(journal)
    rep = st.session_state.get("integrity")
    if rep:
        (st.success if rep.ok else st.error)(
            t("audit.integrity_ok", n=rep.entries_checked) if rep.ok
            else t("audit.integrity_bad", problem=rep.problem, n=rep.entries_checked))
    st.write(t("jr.anchor"))
    st.code(last_hash(journal))
    st.caption(t("jr.anchor_caption"))

    st.subheader(t("jr.tamper_title"))
    st.write(t("jr.tamper_text"))
    c1, c2, c3 = st.columns(3)
    if c1.button(t("jr.copy")):
        shutil.copyfile(journal, TAMPER_COPY)
        st.session_state.pop("tamper_report", None)
    target = c2.number_input(t("jr.target"), min_value=1, max_value=len(events), value=min(5, len(events)))
    if c2.button(t("jr.tamper"), disabled=not TAMPER_COPY.exists()):
        con = sqlite3.connect(TAMPER_COPY)
        con.execute("DROP TRIGGER IF EXISTS journal_no_update")
        con.execute("UPDATE journal SET decision = 'HACKED' WHERE entry_id = ?", (int(target),))
        con.commit()
        con.close()
        st.session_state["tampered"] = int(target)
    if c3.button(t("jr.verify_copy"), disabled=not TAMPER_COPY.exists()):
        st.session_state["tamper_report"] = verify_journal(TAMPER_COPY)
    if "tampered" in st.session_state:
        st.warning(t("jr.tampered", n=st.session_state["tampered"]))
    t_rep = st.session_state.get("tamper_report")
    if t_rep:
        (st.success if t_rep.ok else st.error)(t_rep.problem if t_rep.ok else t("jr.detected", problem=t_rep.problem))
