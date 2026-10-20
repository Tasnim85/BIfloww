"""Ahmed: table profiling and reproducible payment anomaly detection."""
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.audit import AuditEvent, log_event
from .models import AnomalyReport, ProfileReport


def run(ctx: RunContext) -> AgentResult:
    try:
        if ctx.agent != "profiling" or ctx.inputs["tables"].name != "tables":
            raise ValueError("Expected profiling context and masked tables directory")
        if ctx.inputs["tables"].parent.name != "pii":
            raise ValueError("Profiling must consume pii/tables, never raw CSV")
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        profiles = {}
        for path in sorted(ctx.inputs["tables"].glob("*.parquet")):
            df = pd.read_parquet(path)
            profiles[path.stem] = {"rows": len(df), "duplicate_rows": int(df.duplicated().sum()), "columns": {col: {"dtype": str(df[col].dtype), "missing": int(df[col].isna().sum()), "distinct": int(df[col].nunique())} for col in df}}
        if not profiles:
            raise ValueError("No masked Parquet input")
        payments = pd.read_parquet(ctx.inputs["tables"] / "order_payments.parquet")
        columns = ["payment_value", "payment_installments", "payment_sequential"]
        values = payments[columns].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if len(values) < 2:
            raise ValueError("At least two payments are required to train anomaly detection")
        model = Pipeline([("imputer", SimpleImputer(strategy="median", keep_empty_features=True)), ("isolation_forest", IsolationForest(random_state=42, n_estimators=100, contamination=float(ctx.params.get("contamination", 0.01))))])
        model.fit(values)
        scores = payments[["order_id", "payment_sequential"]].copy()
        scores["anomaly_score"] = -model.score_samples(values)
        scores["is_anomaly"] = model.predict(values) == -1
        scores["invalid_amount"] = values["payment_value"].isna() | (values["payment_value"] < 0)
        scores["is_anomaly"] |= scores["invalid_amount"]
        outputs = {"profile": ctx.output_dir / "profile_report.json", "anomalies": ctx.output_dir / "anomaly_report.json", "model": ctx.output_dir / "anomaly_model.joblib", "scores": ctx.output_dir / "anomaly_scores.parquet"}
        outputs["profile"].write_text(ProfileReport(tables=profiles).model_dump_json(indent=2), encoding="utf-8")
        outputs["anomalies"].write_text(AnomalyReport(table="order_payments", features=columns, rows=len(values), flagged=int(scores.is_anomaly.sum()), seed=42, policy="flag_only_never_delete").model_dump_json(indent=2), encoding="utf-8")
        joblib.dump(model, outputs["model"])
        scores.to_parquet(outputs["scores"], index=False)
        log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="detect_payment_anomalies", inputs=[str(ctx.inputs["tables"])], outputs=[str(p) for p in outputs.values()], decision="flag_only", rule_version="anomaly:iforest@1.0", evidence={"rows": len(values), "flagged": int(scores.is_anomaly.sum())}), ctx.output_dir.parent / "audit_journal.jsonl")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS, outputs=outputs)
    except Exception as exc:
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, message=str(exc))
