"""artifact_validator.py — Centralized output artifact integrity & contract validator.

Used both immediately post-execution and before DAG step resumption.
Verifies:
  1. Canonical path & Run isolation: artifact must resolve strictly inside runs/<run_id>/<step_name>/.
  2. Expected nature: file vs directory matching declaration (trailing '/' indicates directory).
  3. Non-emptiness: files must have size > 0.
  4. Pydantic contract compliance for JSON reports (rejects empty '{}' and missing required fields).
  5. Parquet validity: verifies real table readability using pyarrow (rejects dummy PAR1 and truncated bytes).
  6. DuckDB validity: verifies database connection and table readability.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from contracts.registry import CONTRACT_OF

# When set to "1", skips the real DuckDB connection check (useful in CI/stub environments
# where the duckdb native library is blocked by OS policy, e.g. Windows WDAC).
_SKIP_DUCKDB = os.environ.get("BIFLOW_SKIP_DUCKDB_VALIDATION", "0") == "1"

log = logging.getLogger(__name__)


def validate_single_artifact(
    step_name: str,
    output_key: str,
    declared_filename: str,
    actual_path: Path | str,
    run_id: str,
    runs_root: Path | str,
) -> tuple[bool, str]:
    """Validate a single artifact path against canonical invariants.

    Returns:
        (is_valid, error_reason)
    """
    runs_root_path = Path(runs_root).resolve()
    expected_step_dir = (runs_root_path / run_id / step_name).resolve()
    target_p = Path(actual_path).resolve()

    # 1. Isolation check: must belong strictly to current run and step
    try:
        rel = target_p.relative_to(expected_step_dir)
    except ValueError:
        return False, f"path escape: points outside {expected_step_dir}"

    # 2. Canonical filename check: relative path inside step dir must match declared filename
    expected_rel = declared_filename.rstrip("/")
    if rel.as_posix() != expected_rel:
        return False, f"canonical path mismatch: expected '{expected_rel}', got '{rel.as_posix()}'"

    # 3. Existence check
    if not target_p.exists():
        return False, f"missing file/dir: {declared_filename} at {target_p}"

    # 4. File vs Directory check
    is_dir_expected = declared_filename.endswith("/")
    if is_dir_expected:
        if not target_p.is_dir():
            return False, f"expected directory, got file: {declared_filename}"
        return True, ""

    # From here, file is expected
    if target_p.is_dir():
        return False, f"expected file, got directory: {declared_filename}"

    # 5. Non-empty check
    try:
        size = target_p.stat().st_size
    except OSError as exc:
        return False, f"cannot stat file: {exc}"
    if size == 0:
        return False, f"empty file (0 bytes): {declared_filename}"

    # 6. JSON & Pydantic contract validation
    if declared_filename.endswith(".json"):
        try:
            content = target_p.read_text(encoding="utf-8")
        except Exception as exc:
            return False, f"cannot read JSON file as utf-8: {exc}"

        try:
            parsed = json.loads(content)
        except Exception as exc:
            return False, f"invalid JSON syntax: {exc}"

        ref = f"{step_name}.{output_key}"
        contract_cls = CONTRACT_OF.get(ref)

        # Reject pure empty dict/list if contract is registered or requires fields
        if isinstance(parsed, dict) and len(parsed) == 0:
            if contract_cls is not None:
                return False, f"empty JSON payload ({'{}'}) rejected for registered contract {contract_cls.__name__}"
            return False, f"empty JSON payload ({'{}'})"

        # Check against registered Pydantic contract
        if contract_cls is not None:
            try:
                contract_cls.model_validate(parsed)
            except Exception as exc:
                return False, f"contract validation failed against {contract_cls.__name__}: {exc}"

        return True, ""

    # 7. Parquet validity check
    if declared_filename.endswith(".parquet"):
        try:
            import pyarrow.parquet as pq
            pq_file = pq.ParquetFile(target_p)
            _ = pq_file.schema
        except Exception as exc:
            return False, f"corrupted or invalid Parquet: {exc}"
        return True, ""

    # 8. DuckDB validity check
    if declared_filename.endswith(".duckdb"):
        if _SKIP_DUCKDB:
            # Stub/CI mode: skip real DuckDB connection (e.g. WDAC blocks native .pyd)
            return True, ""
        try:
            import duckdb
            con = duckdb.connect(str(target_p), read_only=True)
            con.execute("SHOW TABLES").fetchall()
            con.close()
        except Exception as exc:
            return False, f"corrupted or invalid DuckDB: {exc}"
        return True, ""

    return True, ""


def validate_step_artifacts(
    step_name: str,
    run_id: str,
    declared_outputs: dict[str, str],
    actual_outputs: dict[str, Any] | None = None,
    runs_root: Path | str = "runs",
) -> list[str]:
    """Validate all declared artifacts for a step.

    Returns:
        List of validation error messages (empty if all valid).
    """
    errors: list[str] = []
    actual_outputs = actual_outputs or {}
    expected_step_dir = (Path(runs_root).resolve() / run_id / step_name)

    for out_key, filename in declared_outputs.items():
        target_path: Path | str | None = None
        if out_key in actual_outputs:
            val = actual_outputs[out_key]
            if isinstance(val, (str, Path)):
                target_path = val
        if target_path is None:
            clean_name = filename.rstrip("/")
            target_path = expected_step_dir / clean_name

        is_valid, reason = validate_single_artifact(
            step_name=step_name,
            output_key=out_key,
            declared_filename=filename,
            actual_path=target_path,
            run_id=run_id,
            runs_root=runs_root,
        )
        if not is_valid:
            errors.append(f"{out_key}: {reason}")

    return errors
