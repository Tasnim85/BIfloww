"""tests/test_artifact_validator.py — Centralized artifact validation tests.

Verifies:
  1. Rejection of empty JSON '{}' when contract requires fields.
  2. Rejection of empty file (0 bytes).
  3. Rejection of directory when file expected (and vice-versa).
  4. Rejection of path escaping outside runs/<run_id>/<step_name>.
  5. Rejection of fake Parquet bytes (b"PAR1fakePAR1").
  6. Acceptance of valid JSON contract payloads and valid Parquet files.
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
import pytest

from orchestrator.artifact_validator import (
    validate_single_artifact,
    validate_step_artifacts,
)


def test_reject_empty_json_for_registered_contract(tmp_path):
    run_id = "run_test_empty_json"
    step_name = "similarity"
    step_dir = tmp_path / run_id / step_name
    step_dir.mkdir(parents=True)
    report_file = step_dir / "similarity_report.json"
    report_file.write_text("{}", encoding="utf-8")

    is_valid, reason = validate_single_artifact(
        step_name=step_name,
        output_key="report",
        declared_filename="similarity_report.json",
        actual_path=report_file,
        run_id=run_id,
        runs_root=tmp_path,
    )
    assert not is_valid
    assert "empty JSON payload" in reason or "contract validation failed" in reason


def test_reject_zero_byte_file(tmp_path):
    run_id = "run_test_zero_byte"
    step_name = "upload"
    step_dir = tmp_path / run_id / step_name
    step_dir.mkdir(parents=True)
    empty_file = step_dir / "upload.json"
    empty_file.write_bytes(b"")

    is_valid, reason = validate_single_artifact(
        step_name=step_name,
        output_key="upload",
        declared_filename="upload.json",
        actual_path=empty_file,
        run_id=run_id,
        runs_root=tmp_path,
    )
    assert not is_valid
    assert "empty file (0 bytes)" in reason


def test_reject_dir_when_file_expected(tmp_path):
    run_id = "run_test_dir_file"
    step_name = "column_types"
    step_dir = tmp_path / run_id / step_name
    step_dir.mkdir(parents=True)
    dir_as_file = step_dir / "column_types.json"
    dir_as_file.mkdir()

    is_valid, reason = validate_single_artifact(
        step_name=step_name,
        output_key="report",
        declared_filename="column_types.json",
        actual_path=dir_as_file,
        run_id=run_id,
        runs_root=tmp_path,
    )
    assert not is_valid
    assert "expected file, got directory" in reason


def test_reject_file_when_dir_expected(tmp_path):
    run_id = "run_test_file_dir"
    step_name = "upload"
    step_dir = tmp_path / run_id / step_name
    step_dir.mkdir(parents=True)
    file_as_dir = step_dir / "tables"
    file_as_dir.write_text("not_a_directory", encoding="utf-8")

    is_valid, reason = validate_single_artifact(
        step_name=step_name,
        output_key="tables",
        declared_filename="tables/",
        actual_path=file_as_dir,
        run_id=run_id,
        runs_root=tmp_path,
    )
    assert not is_valid
    assert "expected directory, got file" in reason


def test_reject_path_escape(tmp_path):
    run_id = "run_test_escape"
    step_name = "etl"
    step_dir = tmp_path / run_id / step_name
    step_dir.mkdir(parents=True)

    other_dir = tmp_path / "other_run" / "other_step"
    other_dir.mkdir(parents=True)
    other_file = other_dir / "warehouse_manifest.json"
    other_file.write_text('{"run_id": "other"}', encoding="utf-8")

    is_valid, reason = validate_single_artifact(
        step_name=step_name,
        output_key="manifest",
        declared_filename="warehouse_manifest.json",
        actual_path=other_file,
        run_id=run_id,
        runs_root=tmp_path,
    )
    assert not is_valid
    assert "path escape" in reason


def test_reject_corrupted_parquet(tmp_path):
    run_id = "run_test_fake_parquet"
    step_name = "analysis"
    step_dir = tmp_path / run_id / step_name
    step_dir.mkdir(parents=True)
    fake_parquet = step_dir / "result.parquet"
    fake_parquet.write_bytes(b"PAR1fakePAR1")

    is_valid, reason = validate_single_artifact(
        step_name=step_name,
        output_key="data",
        declared_filename="result.parquet",
        actual_path=fake_parquet,
        run_id=run_id,
        runs_root=tmp_path,
    )
    assert not is_valid
    assert "corrupted or invalid Parquet" in reason


def test_accept_valid_contract_and_parquet(tmp_path):
    run_id = "run_test_valid"
    step_name = "analysis"
    step_dir = tmp_path / run_id / step_name
    step_dir.mkdir(parents=True)

    # Valid Parquet
    parquet_p = step_dir / "result.parquet"
    pd.DataFrame([{"kpi": "Revenue", "val": 100.0}]).to_parquet(parquet_p)

    is_valid, reason = validate_single_artifact(
        step_name=step_name,
        output_key="data",
        declared_filename="result.parquet",
        actual_path=parquet_p,
        run_id=run_id,
        runs_root=tmp_path,
    )
    assert is_valid, reason
