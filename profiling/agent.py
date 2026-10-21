"""Ahmed: structural profile, order coverage and independently testable anomaly detection."""
import hashlib
import json
import tempfile
import time
from pathlib import Path

import pandas as pd
from contracts.agent import AgentResult,AgentStatus,RunContext
from contracts.audit import AuditEvent,log_event
from .models import ProfileReport,AnomalyReport,CoverageReport
from .coverage import coverage
from .anomalies import train


def rename(source,target):
    for attempt in range(6):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt==5:
                raise
            time.sleep(.1*(2**attempt))


def run(ctx:RunContext)->AgentResult:
    try:
        source=ctx.inputs["tables"]
        if ctx.agent!="profiling" or source.name!="tables" or source.parent.name!="pii":
            raise ValueError("PROFILING_INPUT: profiling requires protected pii/tables")
        task=ctx.params.get("task","all")
        if task not in {"all","coverage","anomalies"}:
            raise ValueError("PROFILING_TASK: unknown profiling task")
        paths=sorted(source.glob("*.parquet"))
        if not paths:
            raise ValueError("PROFILING_INPUT: no protected tables available")
        frames={p.stem:pd.read_parquet(p) for p in paths}
        fingerprints={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        targets=(["coverage_profile.json"] if task=="coverage" else ["anomaly_report.json","anomaly_model.joblib","anomaly_scores.parquet"] if task=="anomalies" else ["coverage_profile.json","anomaly_report.json","anomaly_model.joblib","anomaly_scores.parquet"])
        if any((ctx.output_dir/name).exists() for name in targets):
            raise ValueError("PROFILING_EXISTS: this task already has results; start a new test")
        ctx.output_dir.mkdir(parents=True,exist_ok=True)
        old_profile=ctx.output_dir/"profile_report.json"
        if old_profile.exists() and json.loads(old_profile.read_text(encoding="utf-8")).get("source_fingerprints")!=fingerprints:
            raise ValueError("PROFILING_CHANGED: inputs differ from the existing profile; start a new test")
        report_path=source.parent/"pii_report.json"
        pii_report=json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        decisions=pii_report.get("classification") or pii_report.get("decisions",[])
        outputs={"profile":old_profile}
        with tempfile.TemporaryDirectory(prefix=".profiling-",dir=ctx.output_dir) as temporary:
            staging=Path(temporary)
            if not old_profile.exists():
                profiles={name:{"rows":len(df),"duplicate_rows":int(df.duplicated().sum()),"columns":{col:{"dtype":str(df[col].dtype),"missing":int(df[col].isna().sum()),"distinct":int(df[col].nunique())} for col in df}} for name,df in frames.items()}
                (staging/"profile_report.json").write_text(ProfileReport(tables=profiles,source_fingerprints=fingerprints).model_dump_json(indent=2),encoding="utf-8")
            if task in {"all","coverage"}:
                table=ctx.params.get("orders_table","orders")
                if table not in frames:
                    raise ValueError("COVERAGE_TABLE: select the file containing orders")
                result=coverage(frames[table],table,ctx.params.get("date_column","order_purchase_timestamp"),ctx.params.get("status_column","order_status"),ctx.params.get("order_id_column","order_id"))
                (staging/"coverage_profile.json").write_text(CoverageReport.model_validate(result).model_dump_json(indent=2),encoding="utf-8")
                outputs["coverage"]=ctx.output_dir/"coverage_profile.json"
            if task in {"all","anomalies"}:
                table=ctx.params.get("anomaly_table","order_payments")
                if table not in frames:
                    raise ValueError("ANOMALY_TABLE: select the file to inspect")
                _,report=train(frames[table],staging,table=table,features=ctx.params.get("features"),id_column=ctx.params.get("anomaly_id_column","order_id"),amount_column=ctx.params.get("amount_column","payment_value"),contamination=ctx.params.get("contamination",.01),decisions=decisions)
                report["source_fingerprints"]=fingerprints
                (staging/"anomaly_report.json").write_text(AnomalyReport.model_validate(report).model_dump_json(indent=2),encoding="utf-8")
                outputs.update(anomalies=ctx.output_dir/"anomaly_report.json",model=ctx.output_dir/"anomaly_model.joblib",scores=ctx.output_dir/"anomaly_scores.parquet")
            published=[]
            try:
                for path in staging.iterdir():
                    target=ctx.output_dir/path.name
                    if target.exists():
                        raise ValueError("PROFILING_EXISTS: refusing to overwrite an existing artifact")
                    rename(path,target)
                    published.append(target)
            except Exception:
                for target in published:
                    target.unlink()
                raise
        log_event(AuditEvent(run_id=ctx.run_id,agent=ctx.agent,step="profiling_"+task,inputs=[str(source)],outputs=[str(p) for p in outputs.values()],decision="flag_only",rule_version="profiling@2.0",evidence={"task":task,"source_fingerprints":fingerprints}),ctx.output_dir.parent/"audit_journal.jsonl")
        return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.SUCCESS,outputs=outputs)
    except ValueError as exc:
        message=str(exc) if str(exc).startswith(("PROFILING_","COVERAGE_","ANOMALY_")) else "PROFILING_INVALID: selected inputs could not be analysed"
        return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.FAILED,message=message)
    except Exception as exc:
        return AgentResult(run_id=ctx.run_id,agent=ctx.agent,status=AgentStatus.FAILED,message=f"PROFILING_FAILED: {type(exc).__name__}")
