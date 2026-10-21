"""upload.py — Step 0: handle CSV upload and write the Upload contract (Samar).

This is the UPLOAD step entrypoint in the DAG.
It receives the file from the Streamlit app and writes:
  runs/<run_id>/upload/upload.json
  runs/<run_id>/upload/tables/<table>.csv
"""
from __future__ import annotations

import shutil
from pathlib import Path

from contracts.agent import AgentResult, AgentStatus, RunContext
from contracts.common import save
from contracts.intake import Upload


def run(ctx: RunContext) -> AgentResult:
    """Upload step: validate the incoming CSV files and write the Upload contract."""
    source_dir: Path = ctx.params.get("source_dir")
    question: str = ctx.params.get("question", "")
    uploaded_by: str = ctx.params.get("uploaded_by", "anonymous")

    if not source_dir or not Path(source_dir).exists():
        ctx.log("upload", "FAILED", evidence={"error": "source_dir missing or not found"})
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.FAILED,
            message="source_dir not provided or does not exist.",
        )

    source_dir = Path(source_dir)
    tables_out = ctx.output_dir / "tables"
    tables_out.mkdir(parents=True, exist_ok=True)

    table_map: dict[str, str] = {}
    for csv_file in source_dir.glob("*.csv"):
        dest = tables_out / csv_file.name
        shutil.copy2(csv_file, dest)
        table_name = csv_file.stem
        table_map[table_name] = csv_file.name

    if not table_map:
        ctx.log("upload", "FAILED", evidence={"error": "No CSV files found"})
        return AgentResult(
            run_id=ctx.run_id, agent=ctx.agent,
            status=AgentStatus.FAILED,
            message="No CSV files found in source_dir.",
        )

    upload = Upload(question=question, tables=table_map, uploaded_by=uploaded_by)
    upload_path = ctx.output("upload")
    save(upload, upload_path)

    ctx.log(
        "upload", "SUCCESS",
        outputs=[str(upload_path)],
        evidence={"tables": list(table_map.keys()), "question": question},
    )

    return AgentResult(
        run_id=ctx.run_id, agent=ctx.agent,
        status=AgentStatus.SUCCESS,
        outputs={"upload": upload_path, "tables": tables_out},
        message=f"Uploaded {len(table_map)} table(s): {', '.join(table_map.keys())}",
    )
