"""A simple upload-and-protect page backed by the project's PII agent."""
import json
import io
import logging
import os
import re
import zipfile
from collections import Counter
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

import pandas as pd
import streamlit as st

from bo2.config import load_local
from bo2.local_llm import local_base_url
from bo2.pii_ui import MAX_DOWNLOAD_BYTES, JobManager, table_preview

st.set_page_config(page_title="BIFlow · Mes données", page_icon="🔒", layout="centered")
load_local()

LABELS = {"keep": "Conservée", "hmac_sha256": "Protégée", "redact_text": "Masquée", "generalize_coordinate": "Localisation simplifiée"}

st.markdown('''<style>
[data-testid="stToolbar"], #MainMenu, footer {display: none;}
[data-testid="stFileUploaderDropzoneInstructions"] > div {display: none;}
[data-testid="stFileUploaderDropzoneInstructions"]::after {content: "Déposez vos fichiers ici"; font-size: 1rem;}
[data-testid="stFileUploaderDropzone"] button[kind="secondary"] > div,
[data-testid="stFileUploaderDropzone"] button[kind="borderlessIcon"] > div {display: none;}
[data-testid="stFileUploaderDropzone"] button[kind="secondary"],
[data-testid="stFileUploaderDropzone"] button[kind="borderlessIcon"] {font-size: 0;}
[data-testid="stFileUploaderDropzone"] button[kind="secondary"]::after,
[data-testid="stFileUploaderDropzone"] button[kind="borderlessIcon"]::after {content: "Choisir mes fichiers"; font-size: .9rem;}
</style>''', unsafe_allow_html=True)


@st.cache_resource
def manager():
    return JobManager()


@st.cache_data(ttl=10, show_spinner=False)
def model_ready():
    try:
        with build_opener(ProxyHandler({})).open(local_base_url() + "/api/tags", timeout=3) as response:
            names = {item["name"] for item in json.load(response).get("models", [])}
        return os.environ.get("OLLAMA_MODEL", "llama3:latest") in names
    except Exception:
        return False


def start_over():
    st.session_state.pop("pii_current_run", None)
    st.session_state["hide_previous_result"] = True
    st.session_state["upload_round"] = st.session_state.get("upload_round", 0) + 1


def friendly_summary(report):
    lines = ["Bilan de protection de vos données", "", f"Fichiers traités : {len(report.tables)}", ""]
    for item in report.classification:
        lines.append(f"{item.table} — {item.column} : {LABELS.get(item.action, 'Protégée')}")
    if report.uncertain_columns:
        lines += ["", "Certains éléments ont été protégés par précaution."]
    return ("\n".join(lines) + "\n").encode("utf-8")


@st.cache_data(show_spinner=False)
def download_bundle(run_id, summary):
    # Keep archive construction with the page so a running server cannot retain
    # an older imported helper signature after a page update.
    folder = manager().run_dir(run_id) / "pii"
    files = sorted((folder / "csv").glob("*.csv"))
    if not files:
        raise ValueError("No protected files available")
    if sum(path.stat().st_size for path in files) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Download exceeds the memory limit")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"csv/{path.name}")
        archive.writestr("bilan.txt", summary)
    return output.getvalue()


def show_results(run_id):
    jobs = manager()
    snapshot = jobs.snapshot(run_id)
    folder = jobs.run_dir(run_id) / "pii"
    result = snapshot["result"] or {}
    if result.get("status") == "failed" or (not result and snapshot["exit_code"] not in {None, 0}):
        message = result.get("message", "")
        if "PII_SAVE_PERMISSION" in message or "PermissionError" in message:
            st.error("Windows a empêché l’enregistrement des fichiers protégés. Fermez les fichiers de résultat ouverts dans une autre application, puis réessayez.")
        else:
            st.error("Le traitement n’a pas pu se terminer. Réessayez dans quelques instants.")
        st.button("Choisir d’autres fichiers", on_click=start_over, key="retry")
        return
    try:
        report = jobs.report(run_id)
    except Exception:
        st.error("Votre résultat ne peut pas être affiché. Veuillez réessayer.")
        return
    if report is None:
        st.info("Votre résultat n’est pas encore disponible.")
        return
    if report.needs_review or result.get("status") == "needs_review":
        st.warning("Certains éléments doivent être vérifiés avant de pouvoir terminer. Aucun fichier à télécharger n’est disponible pour le moment.")
        details = [{"Fichier": item.table, "Information à vérifier": item.column} for item in report.needs_review]
        if details:
            st.dataframe(pd.DataFrame(details), hide_index=True, width="stretch")
        st.button("Choisir d’autres fichiers", on_click=start_over, key="review_again")
        return
    if result.get("status") != "success" or not (folder / "tables").exists():
        st.info("Votre résultat n’est pas encore disponible.")
        return
    st.success("Vos données sont prêtes !")
    counts = Counter(item.action for item in report.classification)
    a, b, c = st.columns(3)
    a.metric("Fichiers traités", len(report.tables))
    b.metric("Informations protégées", sum(counts.values()) - counts["keep"])
    c.metric("Informations conservées", counts["keep"])
    if report.uncertain_columns:
        st.info("Certains éléments ont été protégés par précaution.")
    summary = friendly_summary(report)
    csv_files = sorted((folder / "csv").glob("*.csv"))
    if csv_files:
        try:
            archive = download_bundle(run_id, summary)
            st.download_button("Télécharger mes données protégées", archive,
                               file_name="mes_donnees_protegees.zip", mime="application/zip", type="primary")
        except Exception as exc:
            logging.getLogger(__name__).warning("Protected download unavailable (%s)", type(exc).__name__)
            st.info("Le téléchargement groupé n’est pas disponible pour le moment. Vous pouvez consulter vos résultats et télécharger chaque fichier ci-dessous.")
    else:
        st.warning("Le téléchargement n’a pas pu être préparé. Veuillez réessayer.")
    st.download_button("Télécharger le bilan", summary, file_name="bilan.txt", mime="text/plain")
    with st.expander("Voir ce qui a été protégé"):
        rows = [{"Fichier": item.table, "Information": item.column, "Résultat": LABELS.get(item.action, "Protégée")}
                for item in report.classification]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with st.expander("Consulter mes fichiers", expanded=True):
        tables = sorted((folder / "tables").glob("*.parquet"))
        if tables:
            selected = st.selectbox("Choisissez un fichier", [path.stem for path in tables], key="protected_file")
            st.dataframe(table_preview(folder / "tables" / f"{selected}.parquet"), hide_index=True, width="stretch")
            st.caption("Vous voyez ici les premières lignes. Le téléchargement contient le fichier complet.")
            csv = folder / "csv" / f"{selected}.csv"
            if csv.exists() and csv.stat().st_size <= MAX_DOWNLOAD_BYTES:
                st.download_button("Télécharger ce fichier", csv.read_bytes(), file_name=csv.name, mime="text/csv")
    from bo2.cleaning_ui import show as show_cleaning
    show_cleaning(jobs.run_dir(run_id))
    st.button("Protéger d’autres fichiers", on_click=start_over)


@st.fragment(run_every=2)
def follow_job(run_id):
    state = manager().snapshot(run_id)
    if not state["running"]:
        st.rerun()
    message = "Nous analysons vos fichiers…"
    if "Verification" in state["log"]:
        message = "Nous vérifions la protection de vos informations…"
    if "Application du masquage" in state["log"]:
        message = "Nous préparons vos fichiers protégés…"
    st.status(message, state="running")
    st.caption(f"Temps écoulé : {state['elapsed']} secondes. Vous pouvez patienter sur cette page.")


def main():
    jobs = manager()
    st.caption("BIFlow")
    st.title("Protéger mes données")
    st.write("Ajoutez vos fichiers, puis lancez la protection de vos informations personnelles.")
    current = st.session_state.get("pii_current_run") or jobs.active()
    if not current and not st.session_state.get("hide_previous_result", False):
        # Recover a completed upload after a browser refresh without restarting
        # the model, or showing old sample/test runs on a fresh installation.
        current = next((name for name in jobs.history() if re.fullmatch(r"pii_[0-9a-f]{32}", name)), None)
        if current:
            st.session_state["pii_current_run"] = current
    busy = jobs.active() is not None
    uploads = st.file_uploader("Vos fichiers", type=["csv", "parquet"], accept_multiple_files=True,
                               key=f"files_{st.session_state.get('upload_round', 0)}", disabled=busy)
    ready = model_ready() and len(os.environ.get("BO2_PII_SECRET", "")) >= 32
    if not ready:
        st.warning("Le service n’est pas disponible pour le moment. Réessayez dans quelques instants.")
        if st.button("Réessayer"):
            model_ready.clear()
            st.rerun()
    if st.button("Lancer la protection", type="primary", disabled=not uploads or busy or not ready):
        try:
            run_id = "pii_" + uuid4().hex
            jobs.start(run_id, uploads=[(file.name, file.getvalue()) for file in uploads], policy="redact")
            st.session_state["pii_current_run"] = run_id
            st.session_state["hide_previous_result"] = False
            st.rerun()
        except ValueError:
            st.error("Ces fichiers ne peuvent pas être utilisés ensemble. Vérifiez leurs noms et leur taille, puis réessayez.")
        except OSError:
            st.error("Le traitement n’a pas pu démarrer. Veuillez réessayer.")
    if current:
        st.divider()
        if jobs.snapshot(current)["running"]:
            follow_job(current)
        else:
            show_results(current)


if __name__ == "__main__":
    main()
