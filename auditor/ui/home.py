import streamlit as st

from auditor.ui.data import DEMO_JOURNAL, DRIFT_JOURNAL, llm_status, t
from contracts.common import CONTRACTS_VERSION
from contracts.pipeline import RUNS_ROOT, output_path
from contracts.prompts import all_prompts


def render() -> None:
    st.title(t("home.title"))
    st.caption(t("home.caption"))

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader(t("home.cmp_title"))
        st.write(t("home.cmp_text"))
    with c2:
        st.subheader(t("home.xai_title"))
        st.write(t("home.xai_text"))
    with c3:
        st.subheader(t("home.drift_title"))
        st.write(t("home.drift_text"))

    st.divider()
    for i in range(1, 5):
        st.write(t(f"home.chain{i}"))

    st.divider()
    st.subheader(t("home.state"))
    checks = {
        t("home.inputs"): output_path("run_001", "etl", "warehouse").exists(),
        t("home.demo_journal"): DEMO_JOURNAL.exists(),
        t("home.drift_runs"): DRIFT_JOURNAL.exists(),
    }
    for label, ok in checks.items():
        st.write(f"{'✅' if ok else '❌'} {label}")
    st.write(t("home.llm", status=llm_status()))
    st.write(t("home.contracts", version=CONTRACTS_VERSION, prompts=", ".join(f"`{p.ref}`" for p in all_prompts())))
    if not all(checks.values()):
        st.code("python -m contracts.examples.install\npython -m auditor.dev.make_fake_inputs\n"
                "python -m auditor.dev.seed_demo_journal\npython -m auditor.dev.simulate_runs\n"
                "python -m auditor.drift.monitor", language="bash")
    st.caption(t("home.runs_folder", path=str(RUNS_ROOT.resolve())))
