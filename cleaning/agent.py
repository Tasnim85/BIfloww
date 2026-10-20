"""Ikbel: approved playbooks, conservative conversions and a human-review barrier."""
import json
import os
import tempfile
import time
from uuid import uuid4
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.audit import AuditEvent, log_event
from .llm_rules import Proposal, check_approval, validate_approval
from .models import CleaningReport
from . import llm_rules
from .registry import select, schema, metadata, compatible, load_playbook


def check_protected_rules(proposal, decisions):
    for rule in proposal.rules:
        affected = [item for item in decisions if item.get("table") == rule.table and item.get("column") == rule.column]
        if rule.action != "trim" and any(item.get("action") != "keep" or item.get("semantic_type") in {"INTERNAL_KEY", "BUSINESS_KEY", "PERSONAL_ID", "POSTAL_CODE"} for item in affected):
            raise ValueError("Proposed conversion would alter a protected column or key")


def cleaning_metadata(frames, decisions):
    data = metadata(frames)
    for item in decisions:
        columns = data["tables"].get(item.get("table"), {}).get("columns", {})
        column = item.get("column")
        if item.get("action") != "keep" or item.get("semantic_type") in {"INTERNAL_KEY", "BUSINESS_KEY", "PERSONAL_ID", "POSTAL_CODE"}:
            columns.pop(column, None)
        elif column in columns:
            columns[column]["semantic_type"] = item.get("semantic_type")
    return data


def run(ctx: RunContext) -> AgentResult:
    try:
        if ctx.agent != "cleaning" or ctx.inputs["tables"].parent.name != "pii":
            raise ValueError("Cleaning must consume pii/tables, never raw CSV")
        if (ctx.output_dir / "tables").exists():
            raise ValueError("Completed cleaning outputs cannot be overwritten")
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = ctx.output_dir / "cleaning_report.json"
        source = ctx.inputs["tables"]
        frames = {p.stem: pd.read_parquet(p) for p in source.glob("*.parquet")}
        if not frames:
            raise ValueError("No masked tables")
        if "profile" in ctx.inputs:
            profile = json.loads(ctx.inputs["profile"].read_text(encoding="utf-8"))
            if set(profile["tables"]) != set(frames):
                raise ValueError("Profile does not match the input tables")
            if any(profile["tables"][name]["rows"] != len(frame) for name, frame in frames.items()):
                raise ValueError("Profile row counts do not match the input tables")
        pii_report_path = source.parent / "pii_report.json"
        pii_report = json.loads(pii_report_path.read_text(encoding="utf-8")) if pii_report_path.exists() else {}
        pii_decisions = pii_report.get("classification") or pii_report.get("decisions", [])
        input_schema = schema(frames)
        if ctx.params.get("playbook_mode") == "generate":
            playbook, playbook_path = {}, None
        elif "playbook" in ctx.params:
            playbook_path = Path(ctx.params["playbook"])
            playbook = load_playbook(playbook_path) if playbook_path.is_file() else {}
            # An absent or incompatible selected file triggers local generation.
            fits = isinstance(playbook, dict) and bool(playbook)
            if fits and "rules" not in playbook:
                fits = compatible(playbook, frames)
            if fits and "input_schema" in playbook:
                fits = playbook["input_schema"] == input_schema
            if not fits:
                playbook, playbook_path = {}, None
        else:
            chosen = select(frames, ctx.params.get("playbook_dir", Path(__file__).parent / "playbooks"),
                            ctx.params.get("runs_dir", ctx.output_dir.parent.parent))
            playbook, playbook_path = chosen if chosen else ({}, None)
        saved_proposal = "rules" in playbook
        known = bool(playbook) and not saved_proposal
        proposal = Proposal.model_validate({key: playbook[key] for key in ("name", "version", "rules")}) if saved_proposal else None
        proposal_path = ctx.inputs.get("proposal")
        if proposal_path:
            proposal = Proposal.model_validate_json(proposal_path.read_text(encoding="utf-8"))
        elif not playbook:
            proposal_path = ctx.output_dir / "proposed_rules.json"
            # Keep valid pending proposals stable; retry rejected drafts instead
            # of repeatedly failing on the same unsafe generated conversion.
            if proposal_path.exists():
                try:
                    cached = Proposal.model_validate_json(proposal_path.read_text(encoding="utf-8"))
                    check_protected_rules(cached, pii_decisions)
                except ValueError:
                    if (ctx.output_dir / "approval.json").exists():
                        raise
                    rejected = proposal_path.with_name("rejected_rules_" + uuid4().hex + ".json")
                    proposal_path.rename(rejected)
            if not proposal_path.exists():
                llm_rules.generate(cleaning_metadata(frames, pii_decisions), os.environ.get("OLLAMA_MODEL", "llama3:latest"), proposal_path)
            proposal = Proposal.model_validate_json(proposal_path.read_text(encoding="utf-8"))
        if proposal:
            check_protected_rules(proposal, pii_decisions)
        review = []
        changes = []
        approval = None
        if proposal:
            if saved_proposal and "proposal" not in ctx.inputs:
                approval = validate_approval(proposal, playbook.get("approval", {}))
            elif "approval" not in ctx.inputs:
                review.append({"reason": "human_approval_required", "proposal": str(proposal_path)})
            else:
                approval = check_approval(proposal, ctx.inputs["approval"])
        elif not known:
            review.append({"reason": "unknown_dataset_requires_proposed_rules", "metadata": {name: {"rows": len(df), "columns": list(df.columns)} for name, df in frames.items()}})
        version = f"playbook:{proposal.name}@{proposal.version}" if proposal else f"playbook:{playbook['name']}@{playbook['version']}" if known else "playbook:pending@0.0"
        if not review:
            for name, frame in frames.items():
                before = len(frame)
                if known:
                    for col in frame.select_dtypes(include=["object", "string"]):
                        if playbook["actions"]["trim_strings"]:
                            frame[col] = frame[col].str.strip()
                        if playbook["actions"]["empty_strings_to_null"]:
                            frame[col] = frame[col].replace("", pd.NA)
                    if playbook["actions"]["remove_exact_duplicate_rows"] and name in playbook["deduplicate_tables"]:
                        frame = frame.drop_duplicates().copy()
                    for col in playbook["numeric_columns"].get(name, []):
                        original = frame[col].notna()
                        frame[col] = pd.to_numeric(frame[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
                        invalid = int((original & frame[col].isna()).sum())
                        if invalid:
                            review.append({"table": name, "column": col, "reason": "invalid_numeric", "rows": invalid})
                    for col in playbook["date_columns"].get(name, []):
                        original = frame[col].notna()
                        frame[col] = pd.to_datetime(frame[col], errors="coerce", format="mixed")
                        invalid = int((original & frame[col].isna()).sum())
                        if invalid:
                            review.append({"table": name, "column": col, "reason": "invalid_dates", "rows": invalid})
                if proposal:
                    version = f"playbook:{proposal.name}@{proposal.version}"
                    for rule in proposal.rules:
                        if rule.table != name:
                            continue
                        if rule.column not in frame:
                            raise ValueError(f"Unknown proposed column: {name}.{rule.column}")
                        series = frame[rule.column]
                        if rule.action == "trim":
                            # A proposed string cleanup must not undo approved date/numeric types.
                            if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
                                frame[rule.column] = series.astype("string").str.strip()
                        elif rule.action == "numeric":
                            converted = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
                            if (series.notna() & converted.isna()).any():
                                review.append({"table": name, "column": rule.column, "reason": "proposal_invalid_numeric"})
                            frame[rule.column] = converted
                        elif rule.action == "datetime":
                            converted = pd.to_datetime(series, errors="coerce", format="mixed")
                            if (series.notna() & converted.isna()).any():
                                review.append({"table": name, "column": rule.column, "reason": "proposal_invalid_date"})
                            frame[rule.column] = converted
                        else:
                            if rule.value is None or any(term in rule.column.lower() for term in ("price", "amount", "value", "freight", "payment")):
                                raise ValueError("Constant filling of financial amounts or null constants is forbidden")
                            frame[rule.column] = series.fillna(rule.value)
                        changes.append({"table": name, "column": rule.column, "action": rule.action})
                if known:
                    for col in playbook["critical_nonnegative_columns"].get(name, []):
                        numeric = pd.to_numeric(frame[col], errors="coerce")
                        invalid = numeric.isna() | (numeric < 0)
                        if invalid.any():
                            review.append({"table": name, "column": col, "reason": "invalid_financial_amount", "rows": int(invalid.sum())})
                    for col in playbook["required_values"].get(name, []):
                        if frame[col].isna().any():
                            review.append({"table": name, "column": col, "reason": "missing_required_value", "rows": int(frame[col].isna().sum())})
                frames[name] = frame
                changes.append({"table": name, "rows_before": before, "rows_after": len(frame), "removed_exact_duplicates": before - len(frame)})
            if proposal:
                unknown_tables = {rule.table for rule in proposal.rules} - set(frames)
                if unknown_tables:
                    raise ValueError("Proposed rules refer to absent tables")
        outputs = {"report": report_path}
        if proposal_path:
            outputs["proposal"] = proposal_path
        if not review:
            destination = ctx.output_dir / "tables"
            # Publish a complete set only; a conversion/write failure leaves no partial tables.
            with tempfile.TemporaryDirectory(prefix=".cleaning-", dir=ctx.output_dir) as temporary:
                staging = Path(temporary) / "tables"
                staging.mkdir()
                for name, frame in frames.items():
                    frame.to_parquet(staging / f"{name}.parquet", index=False)
                for attempt in range(4):
                    try:
                        staging.rename(destination)
                        break
                    except PermissionError:
                        if attempt == 3:
                            raise
                        # Windows can briefly hold a freshly written directory.
                        time.sleep(0.1 * (2 ** attempt))
            mapping_path = ctx.output_dir / "row_mapping.json"
            mapping_path.write_text(json.dumps({name: [int(i) for i in frame.index] for name, frame in frames.items()}), encoding="utf-8")
            outputs["row_mapping"] = mapping_path
            outputs["tables"] = destination
            if proposal:
                # The approved new version is run-local; commit it only after team review.
                path = ctx.output_dir / f"{proposal.name}@{proposal.version}.json"
                path.write_text(json.dumps({**proposal.model_dump(), "approval": approval, "input_schema": input_schema}, ensure_ascii=False, indent=2), encoding="utf-8")
                outputs["playbook"] = path
        report_path.write_text(CleaningReport(selection="existing" if playbook_path else "generated", playbook_path=str(playbook_path) if playbook_path else None, playbook_version=version, changes=changes, needs_review=review).model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        for change in changes:
            log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="apply_cleaning_rule", decision="needs_review" if review else "applied", rule_version=version, evidence=change), ctx.output_dir.parent / "audit_journal.jsonl")
        log_event(AuditEvent(run_id=ctx.run_id, agent=ctx.agent, step="cleaning_complete", decision="needs_review" if review else "success", rule_version=version, evidence={"review_items": len(review)}, outputs=[str(p) for p in outputs.values()]), ctx.output_dir.parent / "audit_journal.jsonl")
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.NEEDS_REVIEW if review else AgentStatus.SUCCESS, outputs=outputs)
    except Exception as exc:
        return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=AgentStatus.FAILED, message=str(exc))
