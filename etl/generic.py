"""Dataset-independent, lossless relational warehouse with a reviewed local-LLM plan."""
import hashlib
import itertools
import json
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from bo2.local_llm import request_json
from contracts.agent import AgentResult, AgentStatus
from contracts.warehouse import TransformationReceipt
from contracts.audit import AuditEvent, log_event
from .models import WarehouseManifest
from bo2.artifact_io import read_artifact_text


class TableAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    role: Literal["activity", "reference", "data"]
    purpose: str = Field(min_length=1, max_length=240)


class Design(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization: Literal["single_table", "related_tables", "separate_tables"]
    rationale: str = Field(min_length=1, max_length=1000)
    tables: list[TableAdvice]
    relationships: list[str] = Field(default_factory=list)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(ctx):
    source = ctx.inputs["tables"]
    if ctx.agent != "etl" or source.parent.name != "cleaning":
        raise ValueError("ETL requires cleaned tables")
    report = json.loads(read_artifact_text(ctx.inputs["cleaning_report"]))
    if report.get("needs_review", True):
        raise ValueError("Cleaning requires review")
    paths = sorted(source.glob("*.parquet"))
    if not paths:
        raise ValueError("No cleaned tables")
    frames = {}
    metadata = {}
    hashes = {"cleaning_report.json": digest(ctx.inputs["cleaning_report"])}
    for i, path in enumerate(paths):
        if not path.resolve().is_relative_to(source.resolve()):
            raise ValueError("Table escapes cleaned folder")
        table = f"data_{i + 1:03d}"
        before = digest(path)
        frame = pd.read_parquet(path)
        if digest(path) != before:
            raise ValueError("Source changed during loading")
        hashes[path.name] = before
        if not len(frame.columns) or any(not isinstance(c, str) or not c or "\x00" in c for c in frame.columns):
            raise ValueError("Table needs named columns")
        if len({c.casefold() for c in frame}) != len(frame.columns):
            raise ValueError("Column names differ only by case or are duplicated")
        frames[table] = frame
        metadata[table] = {"source": path.stem, "rows": len(frame), "primary_key": [],
            "columns": {c: {"dtype": str(frame[c].dtype), "missing": int(frame[c].isna().sum())} for c in frame}}
    # Keys need every table: a column shared with another table is a key candidate too.
    for table, frame in frames.items():
        shared = {c for c in frame for other, f in frames.items() if other != table and c in f}
        metadata[table]["primary_key"] = key_columns(frame, shared)
    return frames, metadata, hashes


# Words that name an identifier, in English, French, Spanish, German... ("id_client", "num_commande",
# "CustomerID", "order_ref"). Matched on whole words of the column name, not on its ending only.
KEY_WORDS = {"id", "ids", "identifier", "identifiant", "key", "code", "ref", "reference", "uuid", "guid", "num", "no", "nr", "numero", "nummer", "cle"}
# Words of a line number inside a parent ("payment_sequential", "line_no"): only the 2nd part of a key.
PART_WORDS = {"sequential", "sequence", "seq", "line", "ligne", "rank", "position", "item", "index"}


def name_words(column):
    """'order_purchase_timestamp' -> ['order', 'purchase', 'timestamp']; 'CustomerID' -> ['customer', 'id']."""
    import re
    import unicodedata
    plain = unicodedata.normalize("NFKD", column).encode("ascii", "ignore").decode()
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", plain)
    return [w for w in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if w]


def is_key_name(column):
    return bool(KEY_WORDS & set(name_words(column)))


def key_columns(frame, shared=frozenset()):
    """Smallest unique, complete combination of identifier-like columns (1 to 3 columns)."""
    usable = [c for c in frame if not pd.api.types.is_float_dtype(frame[c]) and not pd.api.types.is_datetime64_any_dtype(frame[c])
              and not pd.api.types.is_bool_dtype(frame[c])]
    named = [c for c in usable if is_key_name(c)]
    linked = [c for c in usable if c in shared and c not in named]
    parts = [c for c in usable if PART_WORDS & set(name_words(c)) and c not in named and c not in linked]
    candidates = named + linked
    for size in range(1, 4):
        for combo in itertools.combinations(candidates + parts, size):
            if not set(combo) & set(candidates) or (size == 1 and combo[0] in parts):
                continue
            if len(frame) and not frame[list(combo)].isna().any().any() and not frame.duplicated(list(combo)).any():
                return list(combo)
    return []


def relationships(frames, metadata):
    found = []
    for parent, info in metadata.items():
        keys = info["primary_key"]
        if not keys:
            continue
        for child, frame in frames.items():
            if parent == child or not set(keys).issubset(frame.columns):
                continue
            nonnull = frame[keys].notna().all(axis=1)
            if not nonnull.any():
                continue
            values = pd.MultiIndex.from_frame(frame.loc[nonnull, keys])
            parents = pd.MultiIndex.from_frame(frames[parent][keys])
            # Verified inclusion supports a possible relationship, not its business meaning.
            if values.isin(parents).all():
                found.append({"id": f"r{len(found)+1}", "child": child, "parent": parent,
                              "columns": keys, "matched_rows": int(nonnull.sum()),
                              "unlinked_rows": int((~nonnull).sum()), "cardinality": "many_to_one"})
    return found


def validate_design(design, metadata, candidates):
    names = [table.table for table in design.tables]
    if len(names) != len(set(names)) or set(names) != set(metadata):
        raise ValueError("Plan must include every input table exactly once")
    ids = [item["id"] for item in candidates]
    if len(design.relationships) != len(set(design.relationships)) or not set(design.relationships).issubset(ids):
        raise ValueError("Plan contains unverified relationships")
    if len(metadata) == 1:
        if design.organization != "single_table" or design.relationships:
            raise ValueError("A single table needs a single-table organization")
    elif design.organization == "single_table":
        raise ValueError("Multiple inputs cannot be collapsed")
    elif (design.organization == "related_tables") != bool(design.relationships):
        raise ValueError("Organization must match the verified links selected")


def propose(metadata, candidates):
    # Bound each local-model request; wide tables still load every column below.
    compact = {}
    for name, info in metadata.items():
        columns = list(dict.fromkeys([*info["primary_key"], *list(info["columns"])[:24]]))
        compact[name] = {**info, "columns": {key:info["columns"][key] for key in columns},
                         "additional_columns": len(info["columns"]) - len(columns)}
    if len(compact) > 12:
        advice = []; links = []
        names = list(compact)
        for start in range(0, len(names), 6):
            group = {name:compact[name] for name in names[start:start+6]}
            # Cross-batch links need a later business mapping; never fabricate one.
            local_links = [item for item in candidates if item["child"] in group and item["parent"] in group]
            part = propose(group, local_links)
            validate_design(part, group, local_links)
            advice.extend(part.tables); links.extend(part.relationships)
        return Design(organization="related_tables" if links else "separate_tables",
            rationale="Tous les fichiers sont conservés. Les liens proposés ont été vérifiés par groupe de fichiers ; les autres restent indépendants.",
            tables=advice, relationships=links)
    response = request_json(
        "Design a source-preserving analytical database for ANY tabular domain. Use French for purpose and rationale; purpose at most 8 words and rationale at most 30 words. "
        "Include EVERY supplied table exactly once using its data_ identifier. Assign an activity, reference or data role. "
        "Choose single_table for one input; related_tables only with selected candidate relationship IDs; otherwise separate_tables. "
        "Only select candidate IDs whose matching names AND domain semantics support a relationship. Inclusion alone does not prove meaning. "
        "Never invent relationships, columns, keys, aggregations or SQL. Keep all rows, columns and original types. "
        "No flattening or joins are executed. The organization describes preserved tables and approved relationships, "
        "not a fabricated star schema. If unsure choose separate_tables and no relationships.",
        {"tables": compact, "verified_candidates": candidates[:24], "additional_candidates_not_reviewed": max(0, len(candidates)-24)}, Design)
    # These labels describe structure, so validated facts override an impossible LLM label.
    organization = "single_table" if len(metadata) == 1 else "related_tables" if response.relationships else "separate_tables"
    rationale = "Chaque fichier est conservé avec toutes ses lignes et colonnes. " + (
        "Les liens proposés reposent sur des correspondances vérifiées et restent à valider." if response.relationships else
        "Aucun lien entre fichiers n’est imposé.")
    return response.model_copy(update={"organization": organization, "rationale": rationale})


def run(ctx):
    import duckdb  # deferred: avoid WDAC crash at module load
    temporary = ctx.output_dir / "warehouse.building.duckdb"
    connection = None
    owned = False
    published = []
    success = False
    try:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        if any((ctx.output_dir / name).exists() for name in ("warehouse.duckdb", "warehouse_manifest.json", "receipts.json")):
            raise ValueError("Completed warehouse exists; choose another test")
        frames, metadata, hashes = inventory(ctx)
        candidates = relationships(frames, metadata)
        proposal = ctx.output_dir / "warehouse_proposal.json"
        if proposal.exists():
            envelope = json.loads(proposal.read_text(encoding="utf-8"))
            if envelope["source_fingerprints"] != hashes or envelope["tables"] != metadata or envelope["candidates"] != candidates or envelope["cleaning_source"] != str(ctx.inputs["tables"].parent.resolve()):
                raise ValueError("Cleaned sources changed since proposal; choose another test")
            design = Design.model_validate(envelope["design"])
        else:
            if ctx.params.get("etl_approval"):
                raise ValueError("No proposal to approve")
            design = propose(metadata, candidates)
            validate_design(design, metadata, candidates)
            envelope = {"version": 1, "cleaning_source": str(ctx.inputs["tables"].parent.resolve()),
                "source_fingerprints": hashes, "tables": metadata, "candidates": candidates,
                "design": design.model_dump()}
            proposal.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        validate_design(design, metadata, candidates)
        approval = ctx.params.get("etl_approval")
        if not approval:
            return AgentResult(run_id=ctx.run_id, agent="etl", status=AgentStatus.NEEDS_REVIEW,
                outputs={"proposal": proposal}, message="Review the proposed organization before building")
        if approval != digest(proposal):
            raise ValueError("Approval does not match the displayed proposal")
        if temporary.exists():
            raise ValueError("An unfinished build exists; choose another test")
        selected = [item for item in candidates if item["id"] in design.relationships]
        connection = duckdb.connect(str(temporary)); owned = True
        manifest = {}; receipts = []
        for table, frame in frames.items():
            name = quote(table)
            connection.register("source_data", frame)
            connection.execute(f"CREATE TABLE {name} AS SELECT * FROM source_data")
            keys = metadata[table]["primary_key"]
            if keys:
                connection.execute(f"ALTER TABLE {name} ADD PRIMARY KEY ({', '.join(map(quote, keys))})")
            rows = connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            # Check entire multisets (including duplicates/nulls), not just counts or money columns.
            for left, right in [(name, "source_data"), ("source_data", name)]:
                if connection.execute(f"SELECT count(*) FROM (SELECT * FROM {left} EXCEPT ALL SELECT * FROM {right})").fetchone()[0]:
                    raise ValueError("Warehouse changed source values")
            if rows != len(frame):
                raise ValueError("Warehouse changed source row count")
            columns = [{"name": row[1], "type": row[2]} for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()]
            manifest[table] = {"rows": rows, "grain": "source_row", "primary_key": keys, "columns": columns,
                "physical_sources": {col: [f"main.{table}.{col}"] for col in frame}, "kind": "table"}
            receipts.append(TransformationReceipt(output_table=table, source_tables=[metadata[table]["source"]],
                rows_before=len(frame), rows_after=rows, grain="source_row").model_dump())
            connection.unregister("source_data")
        connection.close(); connection = None
        # Recheck every original fingerprint before publishing any completed artifact.
        _, _, current = inventory(ctx)
        if current != hashes:
            raise ValueError("Cleaned sources changed during preparation")
        warehouse = ctx.output_dir / "warehouse.duckdb"
        payload = WarehouseManifest(warehouse=str(warehouse), tables=manifest, physical_tables={f"main.{k}":v for k,v in manifest.items()},
            reconciliation=None, revenue_catalog_status="owned_by_Rabeb_not_defined_here",
            schema_type=design.organization, schema_selection="llm", schema_recommendation=str(proposal),
            cleaning_source=str(ctx.inputs["tables"].parent.resolve()), source_fingerprints=hashes,
            source_tables={k:v["source"] for k,v in metadata.items()}, relationships=selected,
            table_roles={v.table:v.role for v in design.tables}, quality_checks={"all_rows_preserved":True,"all_values_preserved":True},
            approval_digest=approval).model_dump_json(indent=2)
        outputs = {"warehouse":warehouse, "manifest":ctx.output_dir/"warehouse_manifest.json", "receipts":ctx.output_dir/"receipts.json"}
        for path, content in [(outputs["manifest"], payload), (outputs["receipts"], json.dumps(receipts, indent=2))]:
            staged = path.with_suffix(".building.json")
            try:
                staged.write_text(content, encoding="utf-8"); staged.rename(path); published.append(path)
            finally:
                staged.unlink(missing_ok=True)
        temporary.rename(warehouse); published.append(warehouse)
        log_event(AuditEvent(run_id=ctx.run_id, agent="etl", step="build_generic_warehouse", decision="success",
            rule_version="etl-generic@1.0", evidence={"tables":len(frames),"approved_proposal_sha256":approval}), ctx.journal)
        success = True
        return AgentResult(run_id=ctx.run_id, agent="etl", status=AgentStatus.SUCCESS, outputs=outputs,
            message="Built reviewed warehouse; all input tables and values preserved")
    except Exception as exc:
        # Persist diagnostic category only; database conversion errors may contain private source values.
        return AgentResult(run_id=ctx.run_id, agent="etl", status=AgentStatus.FAILED,
            message=f"GENERIC_ETL_{type(exc).__name__}: preparation could not complete; check proposal and cleaned inputs")
    finally:
        if connection is not None:
            connection.close()
        if owned:
            temporary.unlink(missing_ok=True)
        if not success:
            for path in published:
                path.unlink(missing_ok=True)
