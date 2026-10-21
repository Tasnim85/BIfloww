"""Rabeb's BLOCKS for the pipeline's result screen (Samar's app), like Tasnim's components.

Each block takes a run id and draws one part of the Analyst's answer. Display only:
the Analyst (analysis/analyst.py) does the work and writes analysis_result.json.

    kpi_header(run_id)          the number: value, comparison, KPI version, validated or not
    insights_box(run_id)        what explains the result, with the facts behind each sentence
    validation_panel(run_id)    the 4 BO3-03 checks with their numbers
    sql_box(run_id)             the exact SQL, built from the catalog

`key` makes the widgets unique when a block is used twice on one screen.
"""
from pathlib import Path

import streamlit as st

from analysis.ui.data import insight_source, read
from analysis.ui.texts import t
from contracts.audit import DEFAULT_JOURNAL


def kpi_header(run_id: str, key: str = "kpi") -> None:
    r = read(run_id, "analysis.result")
    if r is None:
        st.info(t("run.no_result"))
        return
    req = r.request
    c1, c2, c3 = st.columns(3)
    c1.metric(t("kpi.value", kpi=r.kpi.split("@")[0], start=req.period.start, end=req.period.end),
              f"{r.value_current:,.2f} {r.unit}",
              f"{r.change_pct:+.1%}" if r.change_pct is not None else None)
    if req.compare_to is not None and r.value_previous is not None:
        c2.metric(t("kpi.previous", start=req.compare_to.start, end=req.compare_to.end),
                  f"{r.value_previous:,.2f} {r.unit}")
    c3.metric(t("kpi.version"), r.kpi)
    failed = [c.name for c in r.validations if not c.passed]
    if failed:
        st.error(t("kpi.invalid", failed=", ".join(t(f"checks.name.{n}") for n in failed)))
    else:
        st.success(t("kpi.valid", n=len(r.validations)))


def insights_box(run_id: str, journal: Path = DEFAULT_JOURNAL, key: str = "insights") -> None:
    r = read(run_id, "analysis.result")
    if r is None:
        return
    st.subheader(t("insights.title"))
    if not r.insights:
        st.info(t("insights.none"))
        return
    source = insight_source(run_id, journal)
    st.caption(t("insights.llm") if source == "llm" else t("insights.fallback"))
    for i, ins in enumerate(r.insights):
        st.markdown(f"- {ins.text}")
        if source == "llm" and ins.evidence:
            with st.expander(t("insights.facts"), expanded=False):
                for fact_id, fact in ins.evidence.items():
                    st.markdown(f"`{fact_id}` {fact}")


def validation_panel(run_id: str, key: str = "checks") -> None:
    r = read(run_id, "analysis.result")
    if r is None:
        return
    st.subheader(t("checks.title"))
    for c in r.validations:
        icon, state = ("✅", t("checks.passed")) if c.passed else ("⛔", t("checks.failed"))
        with st.expander(f"{icon} {t('checks.name.' + c.name)} — {state}", expanded=not c.passed):
            st.write(c.detail)


def sql_box(run_id: str, key: str = "sql") -> None:
    r = read(run_id, "analysis.result")
    if r is None:
        return
    with st.expander(t("sql.title"), expanded=False):
        st.code(r.sql, language="sql")
