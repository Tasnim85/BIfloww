"""Prepare the selected cleaned data and show warehouse results in plain language."""
import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import duckdb
import streamlit as st
from contracts.agent import RunContext
from etl.build import run
from bo2.artifact_io import read_artifact_text
from etl.generic import digest, quote
from bo2.pii_ui import MAX_DOWNLOAD_BYTES
from bo2.run_paths import selected_folder

ROLES = {"fact":"Table de faits", "dimension":"Dimension", "reference":"Référence complémentaire", "unresolved":"Rôle à confirmer", "activity":"Activité", "data":"Données"}

FILES = ("warehouse.duckdb", "warehouse_manifest.json", "receipts.json")
LABELS = {"dim_customer": "Clients", "dim_product": "Produits", "dim_seller": "Vendeurs",
          "dim_date": "Calendrier", "fact_order_items": "Articles commandés", "fact_payments": "Paiements"}
LAYOUTS = {"constellation": "Constellation — dimensions partagées", "star": "Étoile — une organisation par activité",
           "snowflake": "Flocon — dimensions organisées en niveaux", "analytical_flat":"Faits sans dimensions identifiées", "relational":"Tables conservées sans modélisation analytique confirmée", "single_table": "Un ensemble de données",
           "related_tables": "Fichiers liés, conservés séparément", "separate_tables": "Fichiers conservés séparément"}


def read(path):
    return json.loads(read_artifact_text(path)) if path.is_file() else {}


def ready(root):
    source = selected_folder(root, "cleaning")
    return (read(root / "pii/agent_result.json").get("status") == "success"
            and read(source / "agent_result.json").get("status") == "success"
            and not read(source / "cleaning_report.json").get("needs_review", True)
            and any((source / "tables").glob("*.parquet")))


def new_test(root):
    value = "etl_tests/" + uuid4().hex + "/etl"
    (root / "etl_current_test.json").write_text(json.dumps({"folder": value}), encoding="utf-8")


class EtlJobs:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.futures = {}
        self.lock = threading.Lock()

    def busy(self, root):
        future = self.futures.get(str(root))
        return future is not None and not future.done()

    def start(self, root, approval=None):
        root = Path(root)
        with self.lock:
            if any(not future.done() for future in self.futures.values()):
                raise ValueError("A warehouse job is already active")
            if not ready(root):
                raise ValueError("Validated cleaning is required")
            target = selected_folder(root, "etl")
            if any((target / name).exists() for name in FILES):
                raise ValueError("Completed result exists")
            source = selected_folder(root, "cleaning")
            self.futures[str(root)] = self.pool.submit(self._run, root, source, target, approval)

    @staticmethod
    def _run(root, source, target, approval=None):
        result = run(RunContext(run_id=root.name, agent="etl",
                     inputs={"tables": source / "tables", "cleaning_report": source / "cleaning_report.json"},
                     output_dir=target, params={"schema_mode": "llm", "warehouse_mode": "dimensional", "etl_approval": approval}))
        target.mkdir(parents=True, exist_ok=True)
        (target / "agent_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result


@st.cache_resource
def jobs():
    return EtlJobs()


@st.fragment(run_every=2)
def follow(root):
    if not jobs().busy(root):
        st.rerun()
    st.status("Nous choisissons une organisation adaptée et préparons vos données…", state="running")
    st.caption("Cette préparation peut prendre quelques minutes.")


def bundle(target):
    files = [target / name for name in FILES]
    if not all(path.is_file() for path in files):
        raise ValueError("Incomplete warehouse")
    if sum(path.stat().st_size for path in files) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Download size limit")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.name)
    return data.getvalue()


def results(target):
    manifest = read(target / "warehouse_manifest.json")
    st.success("Vos données sont prêtes pour l’analyse !")
    labels = manifest.get("source_tables") or LABELS
    if manifest.get("source_tables"):
        if manifest.get("modeling_version")==2:
            a,b,c = st.columns(3)
            a.metric("Tables de faits",sum(r=="fact" for r in manifest["table_roles"].values()))
            b.metric("Dimensions",sum(r=="dimension" for r in manifest["table_roles"].values()))
            c.metric("Fichiers sources conservés",len(manifest["source_row_counts"]))
            st.write("**Schéma recommandé par l’assistant :** " + LAYOUTS[manifest["schema_type"]])
            st.caption("Les faits décrivent les événements et les mesures. Les dimensions apportent leur contexte.")
            st.dataframe([{"Table":table,"Données":labels[table],"Rôle":ROLES.get(role,role),"Lignes":manifest["tables"][table]["rows"]}
                for table,role in sorted(manifest["table_roles"].items(),key=lambda item:({"fact":0,"dimension":1,"reference":2,"unresolved":3}.get(item[1],4),item[0]))],hide_index=True,width="stretch")
            with st.expander("Pourquoi cette organisation ?"):
                st.write(manifest["schema_rationale"])
            st.caption("Toutes les valeurs d’origine ont été conservées. Les dimensions supplémentaires peuvent contenir moins de lignes que les fichiers sources.")
            if any(role=="unresolved" for role in manifest["table_roles"].values()):
                st.info("Certains fichiers ont un rôle à confirmer. Ils restent disponibles parmi les résultats.")
        else:
            a, b = st.columns(2)
            a.metric("Fichiers préparés", len(manifest["tables"]))
            b.metric("Lignes conservées", sum(info["rows"] for info in manifest["tables"].values()))
            st.write("**Organisation retenue :** " + LAYOUTS[manifest["schema_type"]])
            st.caption("Ce résultat provient de l’ancienne préparation. Faites une nouvelle préparation pour identifier les faits, les dimensions et le schéma.")
    else:
        a, b, c = st.columns(3)
        a.metric("Ensembles préparés", len(manifest["tables"]))
        b.metric("Articles commandés", manifest["tables"]["fact_order_items"]["rows"])
        c.metric("Paiements conservés", manifest["tables"]["fact_payments"]["rows"])
        st.write("**Organisation retenue :** " + LAYOUTS[manifest["schema_type"]])
        amounts = manifest["reconciliation"]
        st.write("**Vérification du total des paiements**")
        a, b = st.columns(2)
        a.metric("Avant la préparation", amounts["payments_source"])
        b.metric("Après la préparation", amounts["payments_warehouse"])
        st.caption("Les articles et les paiements sont préparés séparément pour éviter de compter plusieurs fois les montants.")
    selected = st.selectbox("Que souhaitez-vous consulter ?", list(labels), format_func=labels.get, key="etl_preview")
    with duckdb.connect(str(target / "warehouse.duckdb"), read_only=True) as connection:
        preview = connection.execute(f"SELECT * FROM {quote(selected)} LIMIT 100").fetchdf()
    st.dataframe(preview, hide_index=True, width="stretch")
    st.caption("Aperçu des 100 premières lignes au maximum. Les fichiers téléchargés contiennent toutes les lignes.")
    with st.expander("Voir les vérifications effectuées"):
        receipts = {item["output_table"]: item for item in read(target / "receipts.json")}
        st.dataframe([{"Ensemble": labels[name], "Lignes d’origine": receipts[name]["rows_before"],
                       "Lignes préparées": receipts[name]["rows_after"]} for name in labels],
                     hide_index=True, width="stretch")
        if manifest.get("source_tables"):
            st.write("Toutes les valeurs ont été comparées aux fichiers nettoyés.")
            links = manifest.get("relationships", [])
            if links:
                st.dataframe([{"Fichier":labels[link["child"]], "Lié à":labels[link["parent"]],
                    "Informations communes":", ".join(link["columns"])} for link in links], hide_index=True, width="stretch")
        else:
            st.caption("Le calendrier est créé à partir des dates des commandes ; son nombre de lignes peut être différent.")
    try:
        st.download_button("Télécharger mes données préparées", bundle(target), file_name="donnees_preparees.zip",
                           mime="application/zip", key="download_etl")
    except (OSError, ValueError):
        st.info("Le téléchargement groupé n’est pas disponible pour ce résultat.")


def show(root):
    root = Path(root)
    st.divider()
    st.subheader("Préparer mes données pour l’analyse")
    st.write("Regroupez vos fichiers nettoyés dans une organisation adaptée à leur analyse.")
    try:
        target = selected_folder(root, "etl")
        source = selected_folder(root, "cleaning")
        is_ready = ready(root)
        if jobs().busy(root):
            follow(root)
            return
        result = read(target / "agent_result.json")
        if result.get("status") == "success":
            manifest = read(target / "warehouse_manifest.json")
            if manifest.get("cleaning_source") != str(source.resolve()):
                st.info("Ce résultat provient d’un précédent nettoyage. Lancez une nouvelle préparation pour utiliser votre sélection actuelle.")
            results(target)
        elif result.get("status") == "needs_review":
            proposal = target / "warehouse_proposal.json"
            plan = read(proposal)
            st.info("Vérifiez l’organisation proposée avant de continuer.")
            st.write(plan["design"]["rationale"])
            roles = ROLES
            if plan.get("version")==2:
                st.write("**Schéma recommandé par l’assistant :** "+LAYOUTS[plan["design"]["schema_type"]])
            st.dataframe([{"Fichier":plan["tables"][item["table"]]["source"],
                "Lignes":plan["tables"][item["table"]]["rows"], "Rôle proposé":roles[item["role"]]} for item in plan["design"]["tables"]],
                hide_index=True, width="stretch")
            if plan.get("version")==2:
                with st.expander("Voir les mesures et les dates proposées"):
                    st.dataframe([{"Fichier":plan["tables"][item["table"]]["source"],"Une ligne représente":item["grain"],
                        "Mesures":", ".join(item["measures"]),"Dates":", ".join(item["dates"])} for item in plan["design"]["tables"]],hide_index=True,width="stretch")
            links = [link for link in plan["candidates"] if link["id"] in plan["design"]["relationships"]]
            if links:
                st.write("**Liens proposés entre vos fichiers**")
                st.dataframe([{"Fichier":plan["tables"][link["child"]]["source"],
                    "Lié à":plan["tables"][link["parent"]]["source"], "Informations communes":", ".join(link["columns"])}
                    for link in links], hide_index=True, width="stretch")
                st.caption("Les correspondances ont été vérifiées. Confirmez aussi qu’elles ont un sens pour vos données.")
            else:
                st.caption("Aucun lien n’est imposé entre vos fichiers.")
            checked = st.checkbox("Je valide cette organisation", key="approve_etl_" + digest(proposal))
            if st.button("Valider et préparer", disabled=not checked or not is_ready, key="approve_etl"):
                jobs().start(root, digest(proposal)); st.rerun()
        elif result.get("status") == "failed":
            st.error("La préparation n’a pas pu se terminer. Vos données nettoyées restent disponibles.")
            st.caption("Vérifiez que le service est disponible et que le nettoyage de vos fichiers est terminé.")
        if not is_ready:
            st.info("Terminez et validez le nettoyage de vos fichiers pour continuer.")
            return
        if result:
            if st.button("Faire une nouvelle préparation", key="new_etl_test"):
                new_test(root)
                st.rerun()
        elif st.button("Préparer mes données", type="primary", key="start_etl"):
            jobs().start(root)
            st.rerun()
    except (OSError, ValueError, KeyError, duckdb.Error):
        st.error("Ce résultat n’est pas disponible pour le moment. Réessayez dans quelques instants.")
