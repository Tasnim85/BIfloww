"""Local-LLM dimensional design, constrained by verified source structure."""
from typing import Literal
import pandas as pd
import math
import re
from enum import Enum
from pydantic import create_model
from pydantic import BaseModel, ConfigDict, Field
from bo2.local_llm import request_json
from .generic import is_key_name


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    role: Literal["fact", "dimension", "reference", "unresolved"]
    grain: str = Field(min_length=1, max_length=180)
    measures: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=240)


class RoleBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tables: list[Role]


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_type: Literal["star", "snowflake", "constellation", "analytical_flat", "relational"]
    rationale: str = Field(min_length=1, max_length=1000)
    relationships: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2] = 2
    schema_type: Literal["star", "snowflake", "constellation", "analytical_flat", "relational"]
    rationale: str
    tables: list[Role]
    relationships: list[str]


def profile(frames, metadata):
    result = {}
    for table, frame in frames.items():
        keys = metadata[table]["primary_key"]
        numeric = []; dates = []; categories = []; normalizable = []
        for column in frame:
            series = frame[column]
            key_like = column in keys or is_key_name(column)
            identifier_hint = any(word in column.lower().split("_") for word in ["zip", "postal", "sequential", "sequence", "code", "prefix"])
            if not key_like and not identifier_hint and not pd.api.types.is_bool_dtype(series) and not pd.api.types.is_datetime64_any_dtype(series):
                parsed_numeric = pd.to_numeric(series, errors="coerce")
                present = series.notna()
                if present.any() and parsed_numeric[present].notna().all() and parsed_numeric[present].map(lambda v: math.isfinite(float(v))).all():
                    numeric.append(column)
            if pd.api.types.is_datetime64_any_dtype(series) or (column not in numeric and (column.lower().endswith("_at") or re.search(r"(^|_)(date|timestamp|datetime)(_|$)", column.lower()))):
                if series.notna().any():
                    parsed = pd.to_datetime(series, format="mixed", errors="coerce", utc=True)
                    if parsed[series.notna()].notna().all():
                        dates.append(column)
            if not key_like and (pd.api.types.is_string_dtype(series) or series.dtype == object):
                try:
                    count = int(series.nunique(dropna=False))
                    if 1 < count <= min(100, max(2, len(frame)//2)) and column not in dates and column not in numeric:
                        categories.append(column)
                        if count < len(frame):
                            normalizable.append(column)
                except TypeError:
                    pass
        result[table] = {"source":metadata[table]["source"], "rows":len(frame), "primary_key":keys,
            "columns":[{"name":c,"type":str(frame[c].dtype)} for c in list(frame)[:40]],
            "numeric_columns":numeric, "valid_date_columns":dates, "categorical_columns":categories,
            "normalizable_columns":normalizable}
    return result


def reachable(start, links):
    paths = {}; queue = [(start, [])]
    while queue:
        node, path = queue.pop(0)
        for link in links:
            parent = link["parent"]
            if link["child"] == node and parent != start and parent not in paths:
                candidate = path + [link]
                paths[parent] = candidate
                if len(candidate) < 4:
                    queue.append((parent,candidate))
    return paths


def options(roles, metadata, links):
    facts = [r for r in roles if r.role == "fact"]
    dims = {r.table for r in roles if r.role == "dimension"}
    reaches = {r.table:set(reachable(r.table,links)) & dims for r in facts}
    generated = any(r.dimensions or r.dates for r in facts)
    linked = any(reaches.values()) or generated
    choices = ["relational"] if not facts else ["analytical_flat"] if not linked else ["star"]
    if linked:
        shared = any(sum(d in ds for ds in reaches.values()) > 1 for d in dims) or sum(bool(r.dates) for r in facts)>1
        if len(facts)>1 and shared:
            choices.append("constellation")
        if any(r.role=="dimension" and metadata[r.table]["normalizable_columns"] and any(r.table in ds for ds in reaches.values()) for r in roles):
            choices.append("snowflake")
    return choices


def validate(plan, metadata, candidates):
    names = [r.table for r in plan.tables]
    if len(names)!=len(set(names)) or set(names)!=set(metadata):
        raise ValueError("Every source table must have exactly one role")
    ids = [link["id"] for link in candidates]
    if len(plan.relationships)!=len(set(plan.relationships)) or not set(plan.relationships).issubset(ids):
        raise ValueError("Unverified relationship")
    for role in plan.tables:
        info = metadata[role.table]
        for field, valid in [(role.measures,info["numeric_columns"]),(role.dates,info["valid_date_columns"]),(role.dimensions,info["categorical_columns"])]:
            if len(field)!=len(set(field)) or not set(field).issubset(valid):
                raise ValueError("Column role is unsupported by source types")
        if role.role!="fact" and (role.measures or role.dates or role.dimensions):
            raise ValueError("Only facts declare measures and derived dimensions")
    selected = [link for link in candidates if link["id"] in plan.relationships]
    if plan.schema_type not in options(plan.tables,metadata,selected):
        raise ValueError("Recommended layout is incompatible with facts and dimensions")


class RoleLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    role: Literal["fact", "dimension", "reference", "unresolved"]
    grain: str = Field(min_length=1,max_length=180)
    reason: str = Field(min_length=1,max_length=240)


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tables: list[RoleLabel]


def propose(metadata, candidates):
    roles = []; names = list(metadata)
    for start in range(0,len(names),3):
        subset = {}
        for name in names[start:start+3]:
            info = metadata[name]
            outgoing = [metadata[e["parent"]]["source"] for e in candidates if e["child"]==name]
            incoming = [metadata[e["child"]]["source"] for e in candidates if e["parent"]==name]
            subset[name] = {**info, "numeric_columns":info["numeric_columns"][:24], "valid_date_columns":info["valid_date_columns"][:12], "categorical_columns":info["categorical_columns"][:12], "references_to":outgoing,"referenced_by":incoming}
        answer = request_json(
            "Assign a dimensional modeling ROLE to EVERY table, exactly once. "
            "fact means event, measurement or transaction: payments, line items, evaluations/reviews with scores, visits, purchases. "
            "dimension means stable descriptive entity: customers, products/catalogue, employees, locations, devices. "
            "Weights, sizes and photo counts on a catalogue describe products: they are NOT transactional facts. "
            "reference means auxiliary lookup/translation. unresolved means insufficient evidence. "
            "Use source meaning, columns, dates, references_to and referenced_by together. "
            "Dates plus numeric scores and an event reference suggest a fact, not a dimension. "
            "A unique identifier referenced by events plus descriptive attributes suggests a dimension. "
            "State the row grain and reason in French, each under 10 words. No SQL.", {"tables":subset}, Labels)
        for label in answer.tables:
            if label.table not in subset:
                raise ValueError("Model invented source table")
            info=metadata[label.table]; fact=label.role=="fact"
            roles.append(Role(**label.model_dump(), measures=info["numeric_columns"] if fact else [],
                dates=info["valid_date_columns"] if fact else [],
                dimensions=[c for c in info["categorical_columns"] if not any(token in c.lower().split("_") for token in ["sequential","sequence","postal","zip","comment","description","text","title"])][:1] if fact and not any(e["child"]==label.table for e in candidates) else []))
    if len(roles)!=len(metadata) or len({r.table for r in roles})!=len(metadata) or {r.table for r in roles}!=set(metadata):
        raise ValueError("Incomplete model classification")
    selected=[]
    # Every candidate gets an explicit boolean decision; an empty default cannot erase all links.
    for start in range(0,len(candidates),16):
        group=candidates[start:start+16]
        decision_model=create_model("RelationshipDecisions",__config__=ConfigDict(extra="forbid"),**{e["id"]:(bool,...) for e in group})
        payload=[{**e,"child_source":metadata[e["child"]]["source"],"parent_source":metadata[e["parent"]]["source"]} for e in group]
        decision=request_json("For EACH already verified many-to-one candidate, return true if its shared identifier and business meaning describe a real relationship; otherwise false. "
            "An order's customer identifier relates orders to customers; line items relate to their order, product and seller. "
            "Scores/evaluations relate to the event evaluated. Equal values alone without meaningful shared identifiers are insufficient. "
            "No SQL and no extra keys.", {"candidates":payload},decision_model)
        selected.extend(key for key,value in decision.model_dump().items() if value)
    selected_links=[e for e in candidates if e["id"] in selected]
    supported=options(roles,metadata,selected_links)
    allowed=Enum("SupportedLayout",{value:value for value in supported},type=str)
    decision_model=create_model("LayoutDecision",__config__=ConfigDict(extra="forbid"),schema_type=(allowed,...),rationale=(str,...))
    choice=request_json("Recommend ONE of the supported layouts for these classified facts and dimensions. "
        "star = independent fact marts with separate dimension copies. constellation = multiple facts sharing dimensions. "
        "snowflake = repeated dimension categories physically normalized into reference tables. "
        "Prefer shared dimensions when multiple events reuse the same descriptive entities. "
        "Use structural evidence only, no claimed benchmarks. Your short French rationale must justify the EXACT chosen schema_type. "
        "Mention row grain preservation. No SQL.",
        {"supported_layouts":supported,"tables":[{"table":r.table,"source":metadata[r.table]["source"],"role":r.role,"measures":r.measures[:6],"dates":r.dates[:3]} for r in roles],"selected_relationships":selected_links},decision_model)
    plan=Plan(schema_type=choice.schema_type.value,rationale=choice.rationale,tables=roles,relationships=selected)
    validate(plan,metadata,candidates)
    return plan
