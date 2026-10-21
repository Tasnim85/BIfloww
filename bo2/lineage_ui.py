"""BO2 lineage viewer with local Neo4j storage and column-level source tracing."""
import io
import json
import threading
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
from contracts.agent import RunContext
from etl.lineage import run
from etl.models import LineageReport
from etl.generic import digest
from etl.neo4j_store import ancestors
from bo2.run_paths import selected_folder, lineage_folder
from bo2.pii_ui import MAX_DOWNLOAD_BYTES
from bo2.artifact_io import read_artifact_text

STAGES={"raw":"Fichier d’origine","pii":"Informations protégées","clean":"Données nettoyées",
        "transformation":"Transformation","physical":"Stockage préparé","warehouse":"Données pour l’analyse","kpi":"Indicateur"}
COLORS={"raw":"#E2E8F0","pii":"#DBEAFE","clean":"#DCFCE7","transformation":"#FEF3C7","physical":"#EDE9FE","warehouse":"#C7D2FE","kpi":"#FCE7F3"}
OPERATIONS={"privacy:keep":"Information conservée","privacy:hmac_sha256":"Identifiant protégé","privacy:redact_text":"Texte masqué",
    "privacy:generalize_coordinate":"Localisation simplifiée","privacy_policy":"Protection des informations",
    "approved_cleaning":"Nettoyage validé","dimensional_etl":"Préparation de la table","cast_numeric_measure":"Conversion en nombre",
    "canonical_table_or_view":"Mise à disposition","verified_dimension_lookup":"Lien avec une dimension","generated_column":"Information créée",
    "row_identity_or_derived_column":"Calcul à partir des lignes","catalog_binding":"Lien fourni par le catalogue","etl":"Préparation"}


def read(path):
    return json.loads(read_artifact_text(path)) if path.is_file() else {}


def folder(root):
    return lineage_folder(root)


def ready(root):
    target=selected_folder(root,"etl")
    return read(target/"agent_result.json").get("status")=="success" and all((target/name).is_file() for name in ["warehouse.duckdb","warehouse_manifest.json","receipts.json"])


def upstream(graph,target):
    ids={n["id"] for n in graph["nodes"]}
    if target not in ids:
        raise ValueError("Unknown trace target")
    parents={}
    for edge in graph["edges"]:
        parents.setdefault(edge["target"],[]).append(edge["source"])
    seen={target};queue=deque([target])
    while queue:
        node=queue.popleft()
        for parent in parents.get(node,[]):
            if parent not in seen:
                seen.add(parent);queue.append(parent)
    return {"nodes":[n for n in graph["nodes"] if n["id"] in seen],"edges":[e for e in graph["edges"] if e["source"] in seen and e["target"] in seen]}


def operation_label(value):
    if value.startswith("cleaning:"):
        actions={"trim":"Espaces inutiles retirés","empty_to_null":"Valeurs vides harmonisées","parse_datetime":"Dates harmonisées", "cast_datetime":"Dates harmonisées",
                 "cast_numeric":"Nombres harmonisés","to_numeric":"Nombres harmonisés","fill_constant":"Valeurs manquantes complétées","drop_exact_duplicates":"Doublons retirés"}
        return " ; ".join(actions.get(action,"Règle de nettoyage validée") for action in value.split(":",1)[1].split(","))
    return OPERATIONS.get(value,"Transformation")


def dot(graph):
    # Labels are escaped strings, never executable Graphviz/HTML supplied by files.
    lines=['digraph lineage {','rankdir=TB; bgcolor="transparent";','node [shape=box, style="rounded,filled", fontname="Arial", fontsize=12];',
           'edge [fontname="Arial", fontsize=9, color="#64748B"];']
    for node in graph["nodes"]:
        body=node["id"].split(":",1)[1]
        if "." in body:
            table,column=body.rsplit(".",1)
            body=table+"\n"+column
        label=STAGES[node["kind"]]+"\n"+body
        lines.append(json.dumps(node["id"])+" [label="+json.dumps(label,ensure_ascii=False)+", fillcolor="+json.dumps(COLORS[node["kind"]])+"];")
    for edge in graph["edges"]:
        lines.append(json.dumps(edge["source"])+" -> "+json.dumps(edge["target"])+" [label="+json.dumps(operation_label(edge["operation"]),ensure_ascii=False)+"];")
    lines.append('}')
    return "\n".join(lines)


class LineageJobs:
    def __init__(self):
        self.pool=ThreadPoolExecutor(max_workers=1);self.futures={};self.lock=threading.Lock()

    def busy(self,root):
        future=self.futures.get(str(root))
        return future is not None and not future.done()

    def start(self,root):
        root=Path(root)
        with self.lock:
            if any(not f.done() for f in self.futures.values()):
                raise ValueError("A lineage build is active")
            if not ready(root):
                raise ValueError("Complete warehouse preparation first")
            etl=selected_folder(root,"etl")
            inputs={"manifest":etl/"warehouse_manifest.json","receipts":etl/"receipts.json","warehouse":etl/"warehouse.duckdb"}
            report=root/"pii/pii_report.json"
            if report.is_file():inputs["privacy_report"]=report
            clean=Path(read(inputs["manifest"])["cleaning_source"])/"cleaning_report.json"
            if clean.is_file():inputs["cleaning_report"]=clean
            destination=folder(root)
            self.futures[str(root)]=self.pool.submit(self._run,root,inputs,destination)

    @staticmethod
    def _run(root,inputs,destination):
        result=run(RunContext(run_id=root.name,agent="lineage",inputs=inputs,output_dir=destination,params={"backend":"neo4j","metric_sources":{}}))
        destination.mkdir(parents=True,exist_ok=True)
        (destination/"agent_result.json").write_text(result.model_dump_json(indent=2),encoding="utf-8")
        return result


@st.cache_resource
def jobs():return LineageJobs()


@st.fragment(run_every=2)
def follow(root):
    if not jobs().busy(root):st.rerun()
    st.status("Nous retraçons la préparation de vos données et enregistrons les liens…",state="running")


def bundle(target):
    names=[n for n in ["lineage.json","neo4j_import.json"] if (target/n).is_file()]
    if not names or sum((target/n).stat().st_size for n in names)>MAX_DOWNLOAD_BYTES:
        raise ValueError("Download unavailable")
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in names:archive.write(target/name,name)
    return output.getvalue()


@st.cache_data(ttl=20,show_spinner=False)
def recorded_sources(run_id,target):
    return ancestors(run_id,target)


def results(root,target):
    graph=LineageReport.model_validate_json(read_artifact_text(target/"lineage.json")).model_dump()
    etl=selected_folder(root,"etl")
    for key,name in [("manifest","warehouse_manifest.json"),("receipts","receipts.json"),("warehouse","warehouse.duckdb")]:
        expected=graph["source_fingerprints"].get(key)
        if expected and digest(etl/name)!=expected:
            st.warning("Les données ont changé depuis la création de ce graphe. Faites une nouvelle préparation pour retracer ces nouvelles données.")
            return
    manifest=read(etl/"warehouse_manifest.json")
    imported=read(target/"neo4j_import.json")
    if imported.get("status")=="success" and imported.get("run_id")==graph["graph_run_id"]:
        st.success("La traçabilité de vos données est enregistrée !")
    else:
        st.warning("Le graphe est disponible ici. Son enregistrement dans le service de traçabilité reste à terminer.")
    a,b=st.columns(2)
    a.metric("Informations suivies",sum(n["kind"]=="warehouse" for n in graph["nodes"]))
    b.metric("Liens de traçabilité",len(graph["edges"]))
    if graph["integration_status"]=="bo2_only":
        st.info("La traçabilité couvre vos fichiers et leur préparation jusqu’aux tables d’analyse. Les indicateurs seront reliés après leur intégration.")
    tables=sorted(manifest["tables"],key=lambda t:(manifest.get("table_roles",{}).get(t)!="fact",t))
    table=st.selectbox("Quelles données voulez-vous retracer ?",tables,format_func=lambda t:manifest.get("source_tables",{}).get(t,t),key="lineage_table")
    columns=[c["name"] for c in manifest["tables"][table]["columns"]]
    columns.sort(key=lambda c:c.startswith("__bi_"))
    bindings={b["warehouse_column"]:b["source_column"]+" (valeur pour l’analyse)" for b in manifest.get("measure_bindings",{}).get(table,[])}
    column=st.selectbox("Quelle information ?",columns,format_func=lambda c:bindings.get(c,c),key="lineage_column")
    selected=upstream(graph,f"warehouse:{table}.{column}")
    if len(selected["nodes"])<=100:
        st.graphviz_chart(dot(selected),width="content")
        st.caption("Suivez les flèches depuis le fichier d’origine jusqu’à l’information utilisée pour l’analyse. Seuls les noms des informations sont affichés.")
    else:
        st.info("Ce parcours contient beaucoup de liens. Consultez la liste des sources ou téléchargez le graphe complet.")
    sources=[n["id"].split(":",1)[1] for n in selected["nodes"] if n["kind"]=="raw"]
    st.write("**Informations d’origine retrouvées**")
    if sources:st.dataframe({"Origine":sources},hide_index=True,width="stretch")
    else:st.caption("Cette information est créée pendant la préparation. Consultez ses transformations dans le graphe.")
    if imported.get("status")=="success":
        if st.button("Vérifier les sources enregistrées",key="verify_lineage"):
            try:
                found=recorded_sources(graph["graph_run_id"],f"warehouse:{table}.{column}")
                if {n["node_id"] for n in found}!={n["id"] for n in selected["nodes"]}:
                    st.warning("Les sources enregistrées et le graphe local diffèrent. Relancez l’enregistrement.")
                else:st.success("Les sources enregistrées correspondent à ce parcours.")
            except Exception:
                st.warning("Le service de traçabilité ne répond pas. Le parcours local reste consultable.")
    st.download_button("Télécharger la traçabilité",bundle(target),file_name="tracabilite.zip",mime="application/zip",key="download_lineage")


def show(root):
    root=Path(root);st.divider();st.subheader("Comprendre l’origine de mes résultats")
    st.write("Retrouvez les fichiers et les étapes qui ont préparé chaque information.")
    try:
        if not ready(root):
            st.info("Terminez la préparation de vos données pour afficher leur traçabilité.");return
        target=folder(root)
        if jobs().busy(root):follow(root);return
        result=read(target/"agent_result.json")
        if (target/"lineage.json").is_file():
            results(root,target)
        if result.get("status")=="failed":
            st.caption("L’enregistrement n’a pas pu se terminer. Vérifiez que le service de traçabilité est démarré, puis réessayez.")
        if not result or result.get("status")=="failed":
            if st.button("Afficher la traçabilité" if not result else "Réessayer l’enregistrement",key="start_lineage",type="primary"):
                jobs().start(root);st.rerun()
    except (OSError,ValueError,KeyError):
        st.error("La traçabilité de ce test ne peut pas être affichée pour le moment.")
