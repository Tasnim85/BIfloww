import streamlit as st

from auditor.ui.data import DEMO_JOURNAL, DRIFT_JOURNAL, llm_status
from contracts.common import CONTRACTS_VERSION
from contracts.pipeline import RUNS_ROOT, output_path
from contracts.prompts import all_prompts


def render() -> None:
    st.title("BIFlow · Auditor & comparaisons")
    st.caption("Partie de Tasnim : BO3 (explicabilité et audit) et BO4-12 (comparaisons trompeuses)")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("BO4-12 · Comparaisons")
        st.write("Avant d'afficher « ce mois-ci contre le mois dernier », vérifier que la "
                 "comparaison est honnête, et proposer une correction justifiée que l'utilisateur confirme.")
    with c2:
        st.subheader("BO3 · Expliquer et tracer")
        st.write("SHAP explique chaque anomalie ; le journal chaîné prouve que rien n'a été modifié ; "
                 "l'agent « pourquoi ? » répond en citant ses preuves.")
    with c3:
        st.subheader("BO3 · Surveiller")
        st.write("Comparer chaque run aux mois de référence pour distinguer « les données ont changé » "
                 "de « un agent a changé », y compris dans le raisonnement du modèle.")

    st.divider()
    st.write("**Chaîne 1 :** Requête → 5 contrôles → correction justifiée → décision de l'utilisateur → journal")
    st.write("**Chaîne 2 :** Décision → explication SHAP → preuve → journal")
    st.write("**Chaîne 3 :** Question → outils (journal, lignage, rapports) → réponse vérifiée avec citations")
    st.write("**Chaîne 4 :** Runs mensuels → référence → alerte → diagnostic de la cause")

    st.divider()
    st.subheader("État de la démo")
    checks = {
        "Entrées de run_001 (profil, modèle, entrepôt)": output_path("run_001", "etl", "warehouse").exists(),
        "Journal de démo (run_001)": DEMO_JOURNAL.exists(),
        "Runs mensuels simulés + journal du drift": DRIFT_JOURNAL.exists(),
    }
    for label, ok in checks.items():
        st.write(f"{'✅' if ok else '❌'} {label}")
    st.write(f"🤖 LLM : {llm_status()}")
    st.write(f"📜 Contrats v{CONTRACTS_VERSION} · prompts : "
             + ", ".join(f"`{p.ref}`" for p in all_prompts()))
    if not all(checks.values()):
        st.code("python -m contracts.examples.install\npython -m auditor.dev.make_fake_inputs\n"
                "python -m auditor.dev.seed_demo_journal\npython -m auditor.dev.simulate_runs\n"
                "python -m auditor.drift.monitor", language="bash")
    st.caption(f"Dossier des runs : {RUNS_ROOT.resolve()}")
