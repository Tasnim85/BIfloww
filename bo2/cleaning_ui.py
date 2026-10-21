"""Background cleaning jobs and a plain-language Streamlit result panel."""
import io
import json
import re
from uuid import uuid4
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import streamlit as st

from cleaning.cleaner import run
from bo2.artifact_io import read_artifact_text
from cleaning.llm_rules import Proposal, approve
from contracts.agent import RunContext
from bo2.pii_ui import MAX_DOWNLOAD_BYTES, table_preview


PLAYBOOK_DIR = Path(__file__).resolve().parents[1] / "cleaning/playbooks"
PLAYBOOKS = {
    "Version 1.0": PLAYBOOK_DIR / "playbook_v1.0.json",
    "Version 2.0": PLAYBOOK_DIR / "playbook_v2.0.json",
}


def current_folder(root):
    from bo2.run_paths import selected_folder
    return selected_folder(root, "cleaning")


def new_test(root):
    name = "cleaning_tests/" + uuid4().hex + "/cleaning"
    (root / "cleaning_current_test.json").write_text(json.dumps({"folder": name}), encoding="utf-8")


class CleaningJobs:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.futures = {}
        self.lock = threading.Lock()

    def busy(self, root):
        future = self.futures.get(str(root))
        return future is not None and not future.done()

    def start(self, root, reviewer=None, playbook=None):
        root = Path(root)
        with self.lock:
            if any(not future.done() for future in self.futures.values()):
                raise ValueError("A cleaning job is already active")
            folder = current_folder(root)
            if (folder / "tables").exists():
                raise ValueError("A completed result already exists")
            inputs = {"tables": root / "pii/tables"}
            pii_result = json.loads((root / "pii/agent_result.json").read_text(encoding="utf-8"))
            if pii_result.get("status") != "success":
                raise ValueError("Protection must finish first")
            if reviewer is not None:
                previous=read(folder/'agent_result.json')
                shared=previous.get('outputs',{}).get('playbook')
                if shared and not (folder/'proposed_rules.json').exists():
                    from contracts.quality import Playbook
                    from contracts import save
                    from datetime import datetime,timezone
                    book=Playbook.model_validate_json(Path(shared).read_text(encoding='utf-8'))
                    approved=book.model_copy(update={'approved_by':reviewer.strip(),'approved_at':datetime.now(timezone.utc)})
                    save(approved,Path(shared))
                    playbook=Path(shared)
                else:
                    inputs["proposal"] = folder / "proposed_rules.json"
                    inputs["approval"] = approve(inputs["proposal"], reviewer, folder / "approval.json")
            params = {"playbook": str(playbook)} if playbook else {"playbook_mode": "generate"}
            params["runs_dir"] = str(root.parent)
            # Keep the original selection when approving or retrying this test.
            selection_file = folder / "selection.json"
            if selection_file.exists():
                params = json.loads(selection_file.read_text(encoding="utf-8"))
            else:
                folder.mkdir(parents=True, exist_ok=True)
                selection_file.write_text(json.dumps(params), encoding="utf-8")
            if reviewer is not None and 'proposal' in inputs:
                # Approval applies only the displayed generated rules, even if a
                # previously missing selected file appears during human review.
                params = {"playbook_mode": "generate", "runs_dir": str(root.parent)}
            self.futures[str(root)] = self.pool.submit(self._run, root, inputs, folder, params)

    @staticmethod
    def _run(root, inputs, folder, params):
        result = run(RunContext(run_id=root.name, agent="cleaning", inputs=inputs, output_dir=folder, params=params))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "agent_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result


@st.cache_resource
def jobs():
    return CleaningJobs()


@st.fragment(run_every=2)
def follow(root):
    if not jobs().busy(root):
        st.rerun()
    st.status("Nous préparons le nettoyage de vos données…", state="running")
    st.caption("Si de nouvelles règles sont nécessaires, leur préparation peut prendre quelques minutes.")


def read(path):
    return json.loads(read_artifact_text(path)) if path.exists() else {}


def show(root):
    root = Path(root)
    folder = current_folder(root)
    st.divider()
    st.subheader("Nettoyer mes données")
    st.write("Choisissez les règles à tester, ou laissez l’assistant en préparer pour vos fichiers.")
    if jobs().busy(root):
        follow(root)
        return
    result = read(folder / "agent_result.json")
    report = read(folder / "cleaning_report.json")
    status = result.get("status")
    if status:
        if st.button("Faire un autre test de nettoyage", key="new_cleaning_test"):
            new_test(root)
            st.session_state.pop("cleaning_playbook_choice", None)
            st.rerun()
    if not status:
        choice = st.selectbox("Règles à utiliser", [None, *PLAYBOOKS],
                              format_func=lambda name: name or "Laisser l’assistant préparer les règles",
                              key="cleaning_playbook_choice")
        descriptions = {
            "Version 1.0": "Enlever les espaces inutiles et les textes vides. Toutes les lignes sont conservées.",
            "Version 2.0": "Nettoyer les textes, reconnaître les nombres et les dates, retirer les lignes strictement identiques dans les fichiers concernés.",
        }
        st.caption(descriptions.get(choice, "De nouvelles règles seront proposées pour votre validation."))
        if choice:
            st.caption("Si ces règles sont absentes ou ne correspondent pas à vos fichiers, l’assistant en proposera de nouvelles.")
        if st.button("Lancer le nettoyage", key="start_cleaning", type="primary"):
            try:
                jobs().start(root, playbook=PLAYBOOKS.get(choice))
                st.rerun()
            except (ValueError, OSError):
                st.error("Le nettoyage n’a pas pu démarrer. Veuillez réessayer.")
        return
    if status == "failed":
        if "protected column or key" in result.get("message", ""):
            st.error("Les règles proposées touchaient des informations déjà protégées. Relancez la préparation pour obtenir de nouvelles règles adaptées.")
        elif "Local Llama 3" in result.get("message", ""):
            st.error("L’assistant n’a pas pu préparer des règles utilisables. Vous pouvez réessayer.")
        else:
            st.error("Le nettoyage n’a pas pu se terminer. Vos fichiers protégés restent disponibles.")
        if st.button("Réessayer le nettoyage", key="retry_cleaning"):
            jobs().start(root)
            st.rerun()
        return
    if status == "needs_review":
        reasons = {item["reason"] for item in report.get("needs_review", [])}
        if reasons == {"human_approval_required"}:
            st.info("De nouvelles règles ont été proposées. Vérifiez-les avant de les appliquer.")
            if not (folder/'proposed_rules.json').exists() and result.get('outputs',{}).get('playbook'):
                from contracts.quality import Playbook
                book=Playbook.model_validate_json(Path(result['outputs']['playbook']).read_text(encoding='utf-8'))
                st.dataframe([{'Fichier':r.table,'Information':r.column or 'Ensemble du fichier','Modification proposée':r.description} for r in book.rules],hide_index=True,width='stretch')
                reviewer=st.text_input('Votre nom pour confirmer la validation',key='cleaning_reviewer')
                if st.button('Valider et appliquer ces règles',disabled=not reviewer.strip(),key='approve_cleaning'):
                    jobs().start(root,reviewer=reviewer)
                    st.rerun()
                return
            proposal = Proposal.model_validate_json((folder / "proposed_rules.json").read_text(encoding="utf-8"))
            labels = {"trim": "Enlever les espaces inutiles", "numeric": "Reconnaître les nombres", "datetime": "Reconnaître les dates", "fill_constant": "Compléter les cases vides"}
            rows = [{"Fichier": rule.table, "Information": rule.column,
                     "Modification proposée": labels[rule.action] + (f" : {rule.value}" if rule.action == "fill_constant" else "")}
                    for rule in proposal.rules]
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            else:
                st.info("L’analyse ne recommande aucune modification. Votre validation conservera vos données telles quelles.")
            reviewer = st.text_input("Votre nom pour confirmer la validation", key="cleaning_reviewer")
            if st.button("Valider et appliquer ces règles", disabled=not reviewer.strip(), key="approve_cleaning"):
                jobs().start(root, reviewer=reviewer)
                st.rerun()
        else:
            st.warning("Certaines informations doivent être vérifiées avant de terminer le nettoyage.")
            rows = [{"Fichier": item.get("table", ""), "Information à vérifier": item.get("column", ""),
                     "Lignes concernées": item.get("rows", "")} for item in report.get("needs_review", [])]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        return
    if status != "success":
        return
    st.success("Vos données nettoyées sont prêtes !")
    st.caption("Les règles choisies ont été appliquées." if report.get("selection") == "existing"
               else "Les règles que vous avez validées ont été appliquées.")
    files = sorted((folder / "tables").glob("*.parquet"))
    changes = [item for item in report.get("changes", []) if "rows_before" in item]
    a, b = st.columns(2)
    a.metric("Fichiers nettoyés", len(files))
    b.metric("Lignes en double retirées", sum(item["removed_exact_duplicates"] for item in changes))
    # Preflight using parquet's uncompressed size before materializing complete CSVs.
    import pyarrow.parquet as pq
    size = sum(pq.ParquetFile(path).metadata.row_group(i).total_byte_size
               for path in files for i in range(pq.ParquetFile(path).metadata.num_row_groups))
    if size <= MAX_DOWNLOAD_BYTES // 4:
        try:
            buffer = io.BytesIO()
            total_bytes = 0
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    content = pd.read_parquet(path).to_csv(index=False).encode("utf-8")
                    total_bytes += len(content)
                    if total_bytes > MAX_DOWNLOAD_BYTES:
                        raise ValueError("Download exceeds memory limit")
                    archive.writestr(path.stem + ".csv", content)
            st.download_button("Télécharger mes données nettoyées", buffer.getvalue(), file_name="mes_donnees_nettoyees.zip", mime="application/zip")
        except Exception:
            st.info("Le téléchargement groupé n’a pas pu être préparé. Vous pouvez consulter vos fichiers ci-dessous.")
    else:
        st.info("Vos fichiers sont prêts. Le téléchargement groupé est trop volumineux pour cette page.")
    if files:
        selected = st.selectbox("Consulter un fichier nettoyé", [path.stem for path in files], key="cleaned_file")
        from bo2.cleaning_comparison import comparison
        source = root / "pii/tables"
        if not (source / f"{selected}.parquet").exists():
            st.dataframe(table_preview(folder / "tables" / f"{selected}.parquet"), hide_index=True, width="stretch")
            return
        try:
            result = comparison(source, folder, selected)
        except Exception:
            st.info("La comparaison n’a pas pu être préparée. Votre fichier nettoyé reste disponible au téléchargement.")
            return
        st.subheader("Avant / Après")
        st.caption("La comparaison commence après la protection de vos informations personnelles.")
        left, right = st.columns(2)
        with left:
            st.write("**Avant le nettoyage**")
            st.caption(f"{result['rows_before']} lignes")
            st.dataframe(result["before"], hide_index=True, width="stretch")
        with right:
            st.write("**Après le nettoyage**")
            st.caption(f"{result['rows_after']} lignes")
            st.dataframe(result["after"], hide_index=True, width="stretch")
        st.caption("Les aperçus affichent au maximum les 100 premières lignes de chaque fichier.")
        if result["sampled"]:
            st.info("Ce fichier est volumineux : la comparaison porte seulement sur les premières lignes disponibles.")
        if not result["aligned"]:
            st.info("Ce résultat ancien ne permet pas de retrouver chaque ligne après les suppressions. Relancez un test pour voir le détail des modifications.")
        elif result["changed"]:
            label = " sur les lignes comparées" if result["sampled"] else ""
            st.write(f"**{result['changed']} valeurs modifiées{label}**")
            st.dataframe(result["details"], hide_index=True, width="stretch")
            st.caption("Jusqu’à 100 modifications sont affichées. Les points · montrent les espaces dans les textes entre guillemets ; Vide indique une valeur absente.")
        else:
            st.info("Aucune valeur modifiée sur les lignes comparées.")
        removed_count = result["rows_before"]-result["rows_after"]
        if removed_count > 0:
            st.write(f"**{removed_count} lignes retirées**")
            if not result["removed"].empty:
                with st.expander("Voir les lignes retirées"):
                    st.dataframe(result["removed"], hide_index=True, width="stretch")
