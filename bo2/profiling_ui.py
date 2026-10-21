"""Plain-language, independent tests for order coverage and unusual numeric values."""
import io
import json
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import streamlit as st
from profiling.profiler import run
from profiling.autodetect import is_key, words
from bo2.artifact_io import read_artifact_text
from contracts.agent import RunContext
from bo2.pii_ui import MAX_DOWNLOAD_BYTES


def read(path):
    return json.loads(read_artifact_text(path)) if path.exists() else {}


def folder(root):
    value=read(root/"profiling_current_test.json").get("folder","")
    return root/value if re.fullmatch(r"profiling_tests/[0-9a-f]{32}/profiling",value) else root/"profiling"


def new_test(root):
    (root/"profiling_current_test.json").write_text(json.dumps({"folder":"profiling_tests/"+uuid4().hex+"/profiling"}),encoding="utf-8")


class ProfilingJobs:
    def __init__(self):
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.futures={}
        self.lock=threading.Lock()

    def busy(self,root):
        future=self.futures.get(str(root))
        return future is not None and not future.done()

    def start(self,root,task,params):
        root=Path(root)
        with self.lock:
            if any(not future.done() for future in self.futures.values()):
                raise ValueError("An analysis is already active")
            if task not in {"coverage","anomalies"} or read(root/"pii/agent_result.json").get("status")!="success":
                raise ValueError("Finish protection before analysis")
            target=folder(root)
            artifact="coverage_profile.json" if task=="coverage" else "anomaly_report.json"
            if (target/artifact).exists():
                raise ValueError("Completed result exists")
            self.futures[str(root)]=self.pool.submit(self._run,root,target,task,params)

    @staticmethod
    def _run(root,target,task,params):
        result=run(RunContext(run_id=root.name,agent="profiling",inputs={"tables":root/"pii/tables"},output_dir=target,params={**params,"task":task}))
        target.mkdir(parents=True,exist_ok=True)
        (target/(task+"_result.json")).write_text(result.model_dump_json(indent=2),encoding="utf-8")
        return result


@st.cache_resource
def jobs():
    return ProfilingJobs()


@st.fragment(run_every=2)
def follow(root):
    if not jobs().busy(root):
        st.rerun()
    st.status("Nous analysons vos fichiers protégés…",state="running")


def download(target,task):
    names=["coverage_profile.json"] if task=="coverage" else ["anomaly_model.joblib","anomaly_scores.parquet","anomaly_report.json"]
    files=[target/name for name in names]
    if not all(path.is_file() for path in files) or sum(path.stat().st_size for path in files)>MAX_DOWNLOAD_BYTES:
        st.info("Le téléchargement groupé n’est pas disponible pour ce résultat.")
        return
    try:
        data=io.BytesIO()
        with zipfile.ZipFile(data,"w",zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path,path.name)
        st.download_button("Télécharger ce bilan" if task=="coverage" else "Télécharger les résultats de détection",data.getvalue(),file_name="bilan_commandes.zip" if task=="coverage" else "resultats_detection.zip",mime="application/zip",key="download_"+task)
    except Exception:
        st.info("Les résultats sont prêts, mais leur téléchargement groupé n’a pas pu être préparé.")


def coverage_results(target):
    report=read(target/"coverage_profile.json")
    st.success("Le bilan de vos commandes est prêt !")
    a,b=st.columns(2)
    a.metric("Commandes analysées",report["total_orders"])
    b.metric("États différents",sum(item["status"] is not None for item in report["orders_by_status"]))
    if report["missing_dates"] or report["invalid_dates"] or report["missing_statuses"]:
        st.info("Certaines commandes ont une date ou un état non renseigné. Elles sont comptées séparément dans le bilan.")
    daily=pd.DataFrame(report["orders_by_day"])
    if not daily.empty:
        dated=daily[daily.date.notna()].copy()
        if not dated.empty:
            dated["date"]=pd.to_datetime(dated.date)
            # Reindex only reasonable calendar spans; gaps remain true zero counts.
            dated=dated.set_index("date")[["orders"]]
            if (dated.index.max()-dated.index.min()).days<=36525:
                dated=dated.reindex(pd.date_range(dated.index.min(),dated.index.max(),freq="D"),fill_value=0)
            st.write("**Commandes par jour**")
            st.line_chart(dated.rename(columns={"orders":"Commandes"}))
        daily=daily.rename(columns={"date":"Jour","orders":"Commandes"}).fillna({"Jour":"Date non renseignée"})
        st.dataframe(daily,hide_index=True,width="stretch")
    statuses=pd.DataFrame(report["orders_by_status"]).rename(columns={"status":"État","orders":"Commandes"})
    if not statuses.empty:
        statuses=statuses.fillna({"État":"État non renseigné"})
        st.write("**Commandes par état**")
        st.bar_chart(statuses.set_index("État"))
        st.dataframe(statuses,hide_index=True,width="stretch")
    with st.expander("Voir les commandes par jour et par état"):
        combined=pd.DataFrame(report["orders_by_day_status"]).rename(columns={"date":"Jour","status":"État","orders":"Commandes"})
        if not combined.empty:
            st.dataframe(combined.fillna({"Jour":"Date non renseignée","État":"État non renseigné"}),hide_index=True,width="stretch")
    download(target,"coverage")


def anomaly_results(target):
    report=read(target/"anomaly_report.json")
    st.success("La recherche de valeurs inhabituelles est terminée !")
    a,b=st.columns(2)
    a.metric("Lignes analysées",report["rows"])
    b.metric("Lignes à vérifier",report["flagged"])
    st.caption("Une ligne signalée mérite une vérification ; elle n’est pas nécessairement erronée. Aucune ligne n’est supprimée.")
    with st.expander("Informations prises en compte"):
        st.write(", ".join(report["features"]))
    file=pq.ParquetFile(target/"anomaly_scores.parquet")
    preview=[]
    for batch in file.iter_batches(batch_size=4096):
        frame=batch.to_pandas()
        frame=frame[frame.is_anomaly]
        if len(frame):
            preview.append(frame.head(100-sum(len(part) for part in preview)))
        if sum(len(part) for part in preview)>=100:
            break
    if preview:
        values=pd.concat(preview,ignore_index=True)
        friendly=pd.DataFrame({"Ligne d’origine":values.source_row+1,"Montant à vérifier":values.invalid_amount,"Information manquante ou invalide":values.invalid_features,"Valeur inhabituelle":values.is_model_anomaly})
        for column in report["features"]:
            friendly[column]=values["input__"+column]
        st.dataframe(friendly,hide_index=True,width="stretch")
        st.caption("Jusqu’à 100 lignes signalées sont affichées. Le téléchargement contient toutes les lignes et leurs résultats.")
    else:
        st.info("Aucune ligne inhabituelle n’a été signalée.")
    st.caption("Le modèle et les informations nécessaires à une prochaine étape d’explication sont enregistrés.")
    download(target,"anomalies")


def choose(label,columns,default,key,optional=False):
    options=[None,*columns]
    return st.selectbox(label,options,index=options.index(default) if default in columns else 0,
                        format_func=lambda value:value or ("Aucun" if optional else "Choisir une information"),key=key)


def show(root):
    root=Path(root);target=folder(root);source=root/"pii/tables"
    paths={path.stem:path for path in sorted(source.glob("*.parquet"))}
    if not paths:
        return
    st.divider();st.subheader("Comprendre mes données")
    st.write("Consultez l’activité de vos commandes et repérez les valeurs qui méritent une vérification.")
    if jobs().busy(root):
        follow(root)
        return
    if any((target/name).exists() for name in ("coverage_profile.json","anomaly_report.json")):
        if st.button("Faire un autre test d’analyse",key="new_profiling_test"):
            new_test(root);st.rerun()
    default_tab="Valeurs inhabituelles" if st.session_state.get("profiling_view")=="anomalies" else "Commandes par jour et par état"
    tabs=st.tabs(["Commandes par jour et par état","Valeurs inhabituelles"],default=default_tab)
    with tabs[0]:
        result=read(target/"coverage_result.json")
        if result.get("status")=="failed":
            st.error("Le bilan n’a pas pu être préparé. Vérifiez le fichier choisi et les informations de commande. Le numéro doit être renseigné et unique.")
        if (target/"coverage_profile.json").exists() and result.get("status")!="failed":
            coverage_results(target)
        else:
            table=st.selectbox("Fichier des commandes",list(paths),index=list(paths).index("orders") if "orders" in paths else 0,key="coverage_table")
            columns=pq.read_schema(paths[table]).names
            defaults={"order_purchase_timestamp","order_status"}.issubset(columns)
            with st.expander("Choisir les informations de commande",expanded=not defaults):
                date=choose("Date de la commande",columns,"order_purchase_timestamp","coverage_date")
                status=choose("État de la commande",columns,"order_status","coverage_status")
                identifier=choose("Numéro de commande",columns,"order_id","coverage_id",optional=True)
                if identifier is None:
                    st.caption("Chaque ligne sera comptée comme une commande.")
            if st.button("Afficher le bilan des commandes",key="start_coverage",disabled=not date or not status):
                st.session_state["profiling_view"]="coverage"
                jobs().start(root,"coverage",{"orders_table":table,"date_column":date,"status_column":status,"order_id_column":identifier})
                st.rerun()
    with tabs[1]:
        result=read(target/"anomalies_result.json")
        if result.get("status")=="failed":
            st.error("La recherche n’a pas pu se terminer. Choisissez des informations numériques utilisables et un fichier contenant au moins deux lignes.")
        if (target/"anomaly_report.json").exists() and result.get("status")!="failed":
            if "shap" not in read(target/"anomaly_report.json"):
                st.info("Ce résultat est ancien. Faites un autre test pour préparer les nouvelles explications.")
            else:
                anomaly_results(target)
        else:
            table=st.selectbox("Fichier à vérifier",list(paths),index=list(paths).index("order_payments") if "order_payments" in paths else 0,key="anomaly_table")
            sample=next(pq.ParquetFile(paths[table]).iter_batches(batch_size=1000),None)
            sample=sample.to_pandas() if sample is not None else pd.DataFrame(columns=pq.read_schema(paths[table]).names)
            decisions=read(source.parent/"pii_report.json")
            decisions=decisions.get("classification") or decisions.get("decisions",[])
            blocked={item["column"] for item in decisions if item.get("table")==table and (item.get("action")!="keep" or item.get("semantic_type") in {"PERSONAL_ID","INTERNAL_KEY","BUSINESS_KEY","POSTAL_CODE"})}
            candidates=[]
            for column in sample:
                # Identifiers in any language (id_client, num_commande, zip codes); a line number such as
                # payment_sequential stays a possible feature, as before.
                if column in blocked or (is_key(column) and not words(column)&{"sequential","seq"}):
                    continue
                values=pd.to_numeric(sample[column],errors="coerce").replace([np.inf,-np.inf],np.nan)
                present=sample[column].notna().sum()
                if present and values.notna().sum()/present>=.8:
                    candidates.append(column)
            defaults=[col for col in ["payment_value","payment_installments","payment_sequential"] if col in candidates]
            features=st.multiselect("Informations à vérifier",candidates,default=defaults or candidates[:5],key="anomaly_features")
            with st.expander("Adapter la recherche"):
                identifier=choose("Numéro pour retrouver la commande",list(sample.columns),"order_id","anomaly_id",optional=True)
                amount=choose("Montant qui ne doit pas être négatif",list(sample.columns),"payment_value","anomaly_amount",optional=True)
                sensitivity=st.slider("Part indicative de lignes inhabituelles (%)",1,20,1,key="anomaly_sensitivity")
                st.caption("La part réelle peut varier. Les informations manquantes ou invalides sont également signalées.")
            st.caption("Les informations protégées et les identifiants sont exclus de la recherche numérique.")
            if st.button("Rechercher les valeurs inhabituelles",key="start_anomalies",disabled=not features):
                st.session_state["profiling_view"]="anomalies"
                jobs().start(root,"anomalies",{"anomaly_table":table,"features":features,"anomaly_id_column":identifier,"amount_column":amount,"contamination":sensitivity/100})
                st.rerun()
