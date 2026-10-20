"""Ikbel: generic local-LLM classification followed by deterministic masking."""
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import pandas as pd

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.audit import AuditEvent, log_event
from . import detection
from .detection import ColumnPrediction
from .models import PiiReport

POLICY = "pii-policy:generic-llama3@2.2"
ACTION = {"EMAIL": "hmac_sha256", "PHONE": "hmac_sha256", "PERSONAL_ID": "hmac_sha256", "POSTAL_CODE": "hmac_sha256", "COORDINATE": "generalize_coordinate"}


def read_tables(source: Path):
    paths = [source] if source.is_file() else sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".parquet"})
    if not paths:
        raise ValueError("No CSV or Parquet input tables")
    frames = {}
    for path in paths:
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        elif path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path)
        else:
            raise ValueError("Supported inputs are CSV and Parquet")
        # Compatibility aliases concern filenames only, not classification rules.
        name = path.stem.removeprefix("olist_").removesuffix("_dataset")
        if name in frames:
            raise ValueError("Input table aliases collide; use unique filenames")
        if frame.columns.duplicated().any() or any(not isinstance(col, str) for col in frame.columns):
            raise ValueError("Columns must have unique string names")
        frames[name] = frame
    return frames


def publish_masked_tables(frames, classification, domains, secret, destination):
    """Apply verified decisions and publish all masked files as one complete set."""
    if destination.exists():
        raise ValueError("Masked outputs already exist")
    expected = {(table, column) for table, frame in frames.items() for column in frame}
    if len(classification) != len(expected) or {(item["table"], item["column"]) for item in classification} != expected:
        raise ValueError("Masking decisions must cover exactly the input columns")
    if any(item["action"] not in {"keep", "hmac_sha256", "redact_text", "generalize_coordinate"} for item in classification):
        raise ValueError("Unsupported masking action")
    staging = destination.with_name("tables.staging")
    staging.mkdir(exist_ok=False)
    planned_actions = {(item["table"], item["column"]): item["action"] for item in classification}
    try:
        for table, frame in frames.items():
            output = frame.copy()
            for column in frame:
                series = frame[column]
                action = planned_actions[(table, column)]
                if action == "hmac_sha256":
                    domain = domains[f"{table}.{column}"]
                    output[column] = series.map(lambda value: hmac.new(secret.encode(), (domain + ":" + str(value)).encode(), hashlib.sha256).hexdigest() if pd.notna(value) else value)
                elif action == "redact_text":
                    output[column] = series.astype("object").where(series.isna(), "[REDACTED]")
                elif action == "generalize_coordinate":
                    output[column] = pd.to_numeric(series, errors="coerce").round(1)
                if action in {"keep", "hmac_sha256"} and series.nunique(dropna=True) != output[column].nunique(dropna=True):
                    raise ValueError("Masking changed the distinct values of a preserved/pseudonymized column")
            output.to_parquet(staging / f"{table}.parquet", index=False)
        for attempt in range(6):
            try:
                staging.rename(destination)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (2 ** attempt))
    finally:
        if staging.exists():
            for path in staging.glob("*.parquet"):
                path.unlink()
            staging.rmdir()


def run(ctx: RunContext) -> AgentResult:
    def progress(message):
        if ctx.params.get("show_progress", False):
            print(f"[PII] {message}", flush=True)

    try:
        if ctx.agent != "pii":
            raise ValueError("Expected agent='pii'")
        secret = os.environ.get("BO2_PII_SECRET", "")
        if len(secret) < 32:
            return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, message="Set BO2_PII_SECRET to a stable secret of at least 32 characters")
        if (ctx.output_dir / "tables").exists():
            raise ValueError("Masked outputs already exist; use a fresh output directory")
        progress("Lecture des fichiers...")
        frames = read_tables(ctx.inputs["tables"])
        hints = {}
        if "column_types" in ctx.inputs:
            hints = json.loads(ctx.inputs["column_types"].read_text(encoding="utf-8"))
            hints = hints.get("tables", hints)
        model = ctx.params.get("llm_model") or os.environ.get("OLLAMA_MODEL", "llama3:latest")
        threshold = float(ctx.params.get("confidence_threshold", 0.75))
        uncertainty_policy = ctx.params.get("uncertain_policy", "review")
        if uncertainty_policy not in {"review", "redact"}:
            raise ValueError("uncertain_policy must be review or redact")
        if not 0 <= threshold <= 1:
            raise ValueError("confidence_threshold must be between zero and one")
        progress(f"Modele local : {model}. Delai maximum par appel : {os.environ.get('OLLAMA_TIMEOUT', '240')} s.")
        predictions = detection.classify_columns(frames, hints=hints, model=model, batch_size=int(ctx.params.get("batch_size", 4)), progress=progress if ctx.params.get("show_progress", False) else None, confidence_threshold=threshold)
        if set(predictions) != set(frames) or any(set(predictions.get(table, {})) != set(frame.columns) for table, frame in frames.items()):
            raise ValueError("PII classifier must cover exactly every input column")
        effective = {}
        for table, frame in frames.items():
            for column in frame:
                prediction = ColumnPrediction.model_validate(predictions[table][column])
                prediction, origin = detection.enforce_contact_signals(frame[column], prediction)
                effective[f"{table}.{column}"] = [prediction, origin]
        # Postal columns may have different names across tables. Share a semantic
        # domain so equal postal values remain joinable without publishing them.
        # Keep exact strings (including leading zeroes), with no lossy normalization.
        domains = {f"{table}.{column}": "semantic:postal_code:v1" if effective[f"{table}.{column}"][0].semantic_type == "POSTAL_CODE" else column.casefold() for table, frame in frames.items() for column in frame}
        shared_names = {}
        for table, frame in frames.items():
            for column in frame:
                shared_names.setdefault(column.casefold(), []).append(f"{table}.{column}")
        for group in shared_names.values():
            if len(group) > 1 and any(effective[key][0].semantic_type == "PERSONAL_ID" for key in group):
                for key in group:
                    current = effective[key][0]
                    if current.semantic_type in {"PERSONAL_ID", "INTERNAL_KEY", "UNKNOWN"}:
                        effective[key] = [ColumnPrediction(semantic_type="PERSONAL_ID", confidence=current.confidence), "shared_key_name"]
        used_keys = set()
        for group in ctx.params.get("key_groups", []):
            if len(group) < 2 or len(group) != len(set(group)) or any(key not in effective or key in used_keys for key in group):
                raise ValueError("key_groups must be disjoint groups of at least two existing table.column names")
            used_keys.update(group)
            sensitive = any(effective[key][0].semantic_type == "PERSONAL_ID" for key in group)
            confidence = min(effective[key][0].confidence for key in group)
            for key in group:
                domains[key] = "declared_key_group:" + hashlib.sha256(json.dumps(sorted(group)).encode()).hexdigest()
                if sensitive:
                    effective[key] = [ColumnPrediction(semantic_type="PERSONAL_ID", confidence=confidence), "key_group"]
        decisions, classification, review = [], [], []
        for table, frame in frames.items():
            for column in frame:
                prediction, origin = effective[f"{table}.{column}"]
                kind = prediction.semantic_type
                action = ACTION.get(kind, "redact_text" if kind in detection.SENSITIVE or kind == "UNKNOWN" else "keep")
                reasons = []
                if kind == "UNKNOWN" or prediction.confidence < threshold:
                    reasons.append("unknown_type" if kind == "UNKNOWN" else "low_confidence")
                if kind == "COORDINATE" and (frame[column].notna() & pd.to_numeric(frame[column], errors="coerce").isna()).any():
                    reasons.append("invalid_coordinate")
                review.extend({"table": table, "column": column, "reason": reason} for reason in reasons)
                if reasons and uncertainty_policy == "redact" and action != "hmac_sha256" and kind != "INTERNAL_KEY":
                    action = "redact_text"
                item = {"table": table, "column": column, "action": action, "non_null_rows": int(frame[column].notna().sum()), "semantic_type": kind, "confidence": prediction.confidence, "classification_source": origin}
                classification.append(item)
                if action != "keep":
                    decisions.append(item)
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = ctx.output_dir / "pii_report.json"
        # Uncertain technical keys must be reviewed; replacing them by a constant
        # would collapse distinct rows and destroy composite/foreign keys.
        technical_keys = {(item["table"], item["column"]) for item in classification if item["semantic_type"] == "INTERNAL_KEY"}
        pending = review if uncertainty_policy == "review" else [item for item in review if (item["table"], item["column"]) in technical_keys]
        report = PiiReport(policy_version=POLICY, model=model, tables={name: len(frame) for name, frame in frames.items()}, decisions=decisions, classification=classification, needs_review=pending, uncertainty_policy=uncertainty_policy, uncertain_columns=review, **detection.prompt_metadata())
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        review_keys = {(item["table"], item["column"]) for item in pending}
        for item in classification:
            log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="classify_column", decision="needs_review" if (item["table"], item["column"]) in review_keys else item["action"], rule_version=POLICY, evidence=item), ctx.output_dir.parent / "audit_journal.jsonl")
        if pending:
            progress(f"Analyse terminee : {len(pending)} point(s) a verifier. Rapport enregistre, tables non publiees.")
            return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.NEEDS_REVIEW, outputs={"report": report_path}, message=f"{len(pending)} column(s) need review; no masked tables published")
        progress("Application du masquage et ecriture des tables Parquet...")
        destination = ctx.output_dir / "tables"
        publish_masked_tables(frames, classification, domains, secret, destination)
        progress(f"Termine : {len(frames)} table(s) protegee(s) dans {destination}.")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.SUCCESS, outputs={"report": report_path, "tables": destination}, message=f"Generic PII classification by {model}; masking complete")
    except Exception as exc:
        # LLM validation errors can contain input values: never persist their text.
        if isinstance(exc, PermissionError):
            progress("Echec d'enregistrement : Windows a refuse l'acces aux fichiers de sortie.")
            return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED,
                               message="PII_SAVE_PERMISSION: Windows denied access while saving protected files")
        progress(f"Echec ({type(exc).__name__}) : verifier Ollama et la configuration.")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, message=f"PII processing failed ({type(exc).__name__}); verify local Ollama, classifier coverage and configuration")
