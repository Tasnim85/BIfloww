"""intake/semantic_detection/step2/schema_reader.py ÔÇö Step 2 Schema Reader.

Owner  : Samar / Malek  (Step 2)
Purpose: Ingest CSV files and JSON schema definitions; extract column metadata
         while preserving all original information for downstream classifiers.

Outputs a list of :class:`ColumnSchema` objects ÔÇö one per column ÔÇö which carry:
  - table name, column name (raw and normalised key)
  - declared dtype (from JSON) or inferred sample dtype (from CSV)
  - nullable flag, sample values, original metadata

The reader is intentionally stateless: call :func:`read_csv_schema` or
:func:`read_json_schema` for one file at a time, or :func:`read_schema_dir`
to process an entire folder.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ÔöÇÔöÇ Data model ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

@dataclass
class ColumnSchema:
    """Metadata for one column extracted from a CSV or JSON schema source."""
    table: str                          # stem of the source file
    column: str                         # original column name (raw)
    position: int                       # 0-based index in source
    declared_type: str | None = None    # type as declared in JSON schema
    sample_values: list[Any] = field(default_factory=list)  # up to 5 raw values
    nullable: bool = True
    source_format: str = "csv"          # "csv" | "json"
    original_metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"ColumnSchema(table={self.table!r}, column={self.column!r}, "
            f"type={self.declared_type!r}, pos={self.position})"
        )


@dataclass
class TableSchema:
    """All columns for one table, plus top-level metadata."""
    table: str
    source_path: str
    source_format: str
    columns: list[ColumnSchema] = field(default_factory=list)
    row_count_hint: int | None = None   # number of data rows seen (CSV only)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def column_names(self) -> list[str]:
        return [c.column for c in self.columns]


# ÔöÇÔöÇ CSV reader ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

_CSV_SAMPLE_ROWS = 5   # how many data rows to read for sample_values


def read_csv_schema(csv_path: Path | str, *, encoding: str = "utf-8") -> TableSchema:
    """Read the header (and a few data rows) from a CSV file.

    Args:
        csv_path: Path to the CSV file.
        encoding: File encoding (default UTF-8).

    Returns:
        A :class:`TableSchema` with one :class:`ColumnSchema` per column.

    Raises:
        FileNotFoundError: if *csv_path* does not exist.
        ValueError: if the file appears empty (no header row).
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    table_name = csv_path.stem
    columns: list[ColumnSchema] = []
    row_count = 0

    with open(csv_path, encoding=encoding, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"CSV file is empty (no header row): {csv_path}")

        # Initialise per-column sample lists
        sample_buckets: list[list[Any]] = [[] for _ in header]

        for row in reader:
            row_count += 1
            if row_count <= _CSV_SAMPLE_ROWS:
                for i, val in enumerate(row):
                    if i < len(sample_buckets):
                        sample_buckets[i].append(val)

    for pos, col_name in enumerate(header):
        columns.append(
            ColumnSchema(
                table=table_name,
                column=col_name,
                position=pos,
                declared_type=None,          # CSV has no declared dtype
                sample_values=sample_buckets[pos],
                nullable=True,               # assume nullable unless stated otherwise
                source_format="csv",
                original_metadata={"header_index": pos},
            )
        )

    return TableSchema(
        table=table_name,
        source_path=str(csv_path),
        source_format="csv",
        columns=columns,
        row_count_hint=row_count,
    )


# ÔöÇÔöÇ JSON schema reader ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
#
# Supported JSON schema flavours:
#
# Flavour A ÔÇö BIFlow native (list of column dicts):
#   [{"column": "order_id", "type": "string", "nullable": false, ...}, ...]
#
# Flavour B ÔÇö Pandas-style (dict with "columns" list):
#   {"table": "orders", "columns": [{"name": "order_id", "dtype": "object"}, ...]}
#
# Flavour C ÔÇö simple column-name list:
#   ["order_id", "customer_id", "price"]
#
# Additional fields are preserved verbatim in `original_metadata`.

def read_json_schema(json_path: Path | str, *, table_name: str | None = None) -> TableSchema:
    """Read a JSON schema file and return a :class:`TableSchema`.

    Args:
        json_path: Path to the JSON file.
        table_name: Override for the table name (defaults to file stem).

    Returns:
        A :class:`TableSchema` populated from the JSON structure.

    Raises:
        FileNotFoundError: if *json_path* does not exist.
        ValueError: if the JSON structure is not recognised.
    """
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON schema file not found: {json_path}")

    with open(json_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    tname = table_name or json_path.stem
    columns: list[ColumnSchema] = []
    raw_meta: dict[str, Any] = {}

    # ÔöÇÔöÇ Flavour A: top-level list of column dicts ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        col_list = raw
        for pos, col_dict in enumerate(col_list):
            col_name = col_dict.get("column") or col_dict.get("name") or col_dict.get("field", f"col_{pos}")
            dtype    = col_dict.get("type") or col_dict.get("dtype")
            nullable = col_dict.get("nullable", True)
            samples  = col_dict.get("samples") or col_dict.get("sample_values", [])
            meta     = {k: v for k, v in col_dict.items()
                        if k not in {"column", "name", "field", "type", "dtype", "nullable", "samples", "sample_values"}}
            columns.append(ColumnSchema(
                table=tname, column=col_name, position=pos,
                declared_type=dtype, sample_values=list(samples),
                nullable=bool(nullable), source_format="json", original_metadata=meta,
            ))

    # ÔöÇÔöÇ Flavour B: {"table": ..., "columns": [...]} ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
    elif isinstance(raw, dict) and "columns" in raw:
        tname = raw.get("table", tname)
        raw_meta = {k: v for k, v in raw.items() if k != "columns"}
        for pos, col_dict in enumerate(raw["columns"]):
            if isinstance(col_dict, str):
                col_dict = {"name": col_dict}
            col_name = col_dict.get("name") or col_dict.get("column", f"col_{pos}")
            dtype    = col_dict.get("dtype") or col_dict.get("type")
            nullable = col_dict.get("nullable", True)
            samples  = col_dict.get("samples", [])
            meta     = {k: v for k, v in col_dict.items()
                        if k not in {"name", "column", "dtype", "type", "nullable", "samples"}}
            columns.append(ColumnSchema(
                table=tname, column=col_name, position=pos,
                declared_type=dtype, sample_values=list(samples),
                nullable=bool(nullable), source_format="json", original_metadata=meta,
            ))

    # ÔöÇÔöÇ Flavour C: simple list of strings ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
    elif isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        for pos, col_name in enumerate(raw):
            columns.append(ColumnSchema(
                table=tname, column=col_name, position=pos,
                source_format="json",
            ))

    else:
        raise ValueError(
            f"Unrecognised JSON schema structure in {json_path}. "
            "Expected a list of column dicts, a dict with 'columns' key, or a list of strings."
        )

    return TableSchema(
        table=tname,
        source_path=str(json_path),
        source_format="json",
        columns=columns,
        raw_metadata=raw_meta,
    )


# ÔöÇÔöÇ Directory reader ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

def read_schema_dir(
    directory: Path | str,
    *,
    csv_encoding: str = "utf-8",
    recurse: bool = False,
) -> list[TableSchema]:
    """Read all CSV and JSON schema files in *directory*.

    Files are processed in alphabetical order.  Sub-directories are ignored
    unless *recurse=True*.

    Args:
        directory: Folder to scan.
        csv_encoding: Encoding passed to :func:`read_csv_schema`.
        recurse: If True, descend into sub-directories.

    Returns:
        List of :class:`TableSchema` objects, one per file successfully read.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    glob_fn = directory.rglob if recurse else directory.glob
    results: list[TableSchema] = []
    errors: list[str] = []

    for path in sorted(glob_fn("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        try:
            if suffix == ".csv":
                results.append(read_csv_schema(path, encoding=csv_encoding))
            elif suffix == ".json":
                results.append(read_json_schema(path))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    if errors:
        import warnings
        warnings.warn(
            f"read_schema_dir: {len(errors)} file(s) could not be read:\n"
            + "\n".join(f"  - {e}" for e in errors),
            stacklevel=2,
        )

    return results
