"""The KPI proposer (Rabeb): a DRAFT KPI catalog + glossary for ANY warehouse, not only Olist.

The Analyst's code knows nothing about Olist: everything specific to a dataset is in
kpi/catalog.yaml and semantic/glossary.yaml. For a new dataset, this tool writes a first
version of these two files, and a human reviews them before the Analyst uses them
(like the schema: the system proposes, a human approves).

    1. CANDIDATES (Python)  read the manifest + the warehouse: every possible measure
                            (COUNT, COUNT DISTINCT of ids, SUM / AVG of numeric columns)
                            and every possible dimension (text columns with few values).
    2. CHOICE (Groq)        the LLM keeps the candidates that make business sense and names
                            them (name, description, unit, synonyms in English and French).
                            It can only pick candidate ids: it never writes a formula.
    3. CHECK (Python)       each proposed KPI is compiled and run on the warehouse.

Without an LLM, every candidate is kept with a mechanical name (sum_fee, count_visits...).
A KPI already in the approved kpi/catalog.yaml keeps its approved name, version, unit and filters.

    python -m analysis.kpi_proposer dev_001
    -> runs/dev_001/analysis/proposal/kpi_catalog_proposal.yaml + glossary_proposal.yaml
"""
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, Field, ValidationError

from analysis.sql_compiler import CompileError, compile_query, find_join_path
from contracts import context_for
from contracts.common import Period
from contracts.pipeline import REPO_ROOT
from contracts.llm import LLMUnavailable, chat_json
from contracts.prompts import load_prompt
from contracts.registry import read_output
from contracts.semantic import (AnalysisRequest, Dimension, Glossary, GlossaryTerm, KpiCatalog,
                                KpiDefinition, load_yaml)
from contracts.warehouse import TableKind, WarehouseManifest

NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL")
MAX_DIMENSION_VALUES = 100        # a text column with more distinct values is not a dimension
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


# ---- 1. CANDIDATES ------------------------------------------------------------------------
@dataclass
class Measure:
    id: str                       # "M1"
    table: str
    expression: str               # e.g. "SUM(fee)"
    default_name: str             # e.g. "sum_fee"
    grain: str
    date_column: str
    allowed: list[str] = field(default_factory=list)   # dimension candidate ids reachable


@dataclass
class DimCandidate:
    id: str                       # "D1"
    table: str
    column: str
    default_name: str
    samples: list[str]


def _is_id(column: str) -> bool:
    return column.lower() == "id" or column.lower().endswith("_id")


def find_candidates(con, manifest: WarehouseManifest) -> tuple[list[Measure], list[DimCandidate]]:
    types = {(t, c): ty.upper() for t, c, ty in con.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns").fetchall()}
    is_num = lambda t, c: types.get((t, c), "").startswith(NUMERIC)

    dims: list[DimCandidate] = []
    for t in manifest.tables:
        for c in t.columns:
            if is_num(t.name, c) or _is_id(c) or c in t.primary_key or c == t.date_column:
                continue
            if not types.get((t.name, c), "").startswith("VARCHAR"):
                continue
            n = con.execute(f'SELECT COUNT(DISTINCT "{c}") FROM {t.name}').fetchone()[0]
            if 2 <= n <= MAX_DIMENSION_VALUES:
                samples = [str(r[0]) for r in con.execute(
                    f'SELECT DISTINCT "{c}" FROM {t.name} WHERE "{c}" IS NOT NULL ORDER BY 1 LIMIT 5').fetchall()]
                dims.append(DimCandidate(f"D{len(dims) + 1}", t.name, c, c, samples))
    for d in dims:                # same column name in two tables: prefix with the table name
        if sum(x.column == d.column for x in dims) > 1:
            d.default_name = f"{d.table.removeprefix('dim_')}_{d.column}"

    measures: list[Measure] = []
    for t in manifest.tables:
        if t.kind != TableKind.FACT or not t.date_column:
            continue
        exprs = [(f"COUNT(*)", f"count_{t.name.removeprefix('fact_')}")]
        exprs += [(f"COUNT(DISTINCT {c})", f"distinct_{c}") for c in t.columns
                  if _is_id(c) and t.primary_key != [c]
                  and not (c in t.primary_key and is_num(t.name, c))]   # a line number (1, 2, 3...)
        for c in t.columns:
            if is_num(t.name, c) and not _is_id(c) and c not in t.primary_key:
                exprs += [(f"SUM({c})", f"sum_{c}"), (f"AVG({c})", f"avg_{c}")]
        reachable = []
        for d in dims:
            try:
                find_join_path(manifest, t, d.table, t.date_column)
                reachable.append(d.id)
            except CompileError:
                pass
        for expr, name in exprs:
            measures.append(Measure(f"M{len(measures) + 1}", t.name, expr, name, t.grain,
                                    t.date_column, reachable))
    return measures, dims


# ---- 2. CHOICE: what the LLM must answer --------------------------------------------------
class ProposedKpi(BaseModel):
    candidate: str                # a measure id, e.g. "M3"
    name: str                     # e.g. "Revenue"
    description: str
    unit: str
    synonyms: list[str] = Field(default_factory=list)


class ProposedDimension(BaseModel):
    candidate: str                # a dimension id, e.g. "D2"
    name: str
    description: str
    synonyms: list[str] = Field(default_factory=list)


class Proposal(BaseModel):
    kpis: list[ProposedKpi]
    dimensions: list[ProposedDimension]


def _describe(measures, dims, manifest, approved: KpiCatalog | None = None) -> str:
    lines = []
    if approved:
        lines += ["ALREADY APPROVED (kept as they are: do not propose the same business concept again,",
                  "and use their units as a hint, e.g. the currency):"]
        lines += [f"- KPI {k.name}: {k.expression} on {k.table}, unit {k.unit}" for k in approved.kpis]
        lines += [f"- dimension {d.name}: {d.table}.{d.column}" for d in approved.dimensions]
        lines += [""]
    lines += ["TABLES:"]
    lines += [f"- {t.name} ({t.kind.value}, one row = one {t.grain}): {', '.join(t.columns)}" for t in manifest.tables]
    lines += ["", "MEASURE CANDIDATES:"]
    lines += [f"- {m.id}: {m.expression} on {m.table} (one row = one {m.grain})" for m in measures]
    lines += ["", "DIMENSION CANDIDATES:"]
    lines += [f"- {d.id}: {d.table}.{d.column}, values like {', '.join(d.samples)}" for d in dims]
    return "\n".join(lines)


def _mechanical(measures, dims) -> Proposal:
    """Without an LLM: keep every candidate, named after its formula."""
    return Proposal(
        kpis=[ProposedKpi(candidate=m.id, name=m.default_name, unit="",
                          description=f"{m.expression} on {m.table} (proposed automatically).")
              for m in measures],
        dimensions=[ProposedDimension(candidate=d.id, name=d.default_name,
                                      description=f"{d.table}.{d.column} (proposed automatically).")
                    for d in dims])


# ---- 3. CHECK + build the catalog ---------------------------------------------------------
def _same(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", a).upper() == re.sub(r"\s+", "", b).upper()


def _build(proposal: Proposal, measures, dims, manifest, con, log,
           approved: KpiCatalog | None = None, approved_glossary: Glossary | None = None) -> tuple[KpiCatalog, Glossary]:
    """approved: the catalog already validated by a human (kpi/catalog.yaml). A candidate that is
    already in it keeps its approved name, version, unit and filters: the proposal never renames
    a KPI the team uses ("Revenue@2.0" stays "Revenue@2.0")."""
    m_by_id, d_by_id = {m.id: m for m in measures}, {d.id: d for d in dims}
    old_kpis = approved.kpis if approved else []
    old_dims = approved.dimensions if approved else []
    used, dim_name = set(), {}
    dimensions, terms = [], []

    def add_dimension(d: DimCandidate, name: str, description: str, synonyms: list[str]):
        old = next((x for x in old_dims if x.table == d.table and x.column == d.column), None)
        if old:
            name, description = old.name, old.description
        if not NAME.match(name) or name in used or d.id in dim_name:
            log(f"dimension refused: {d.id} '{name}' (bad or duplicate name)")
            return
        used.add(name)
        dim_name[d.id] = name
        dimensions.append(Dimension(name=name, table=d.table, column=d.column, description=description))
        terms.append(GlossaryTerm(term=name, kind="dimension", synonyms=synonyms, definition=description))

    for p in proposal.dimensions:
        if p.candidate not in d_by_id:
            log(f"dimension refused: {p.candidate} '{p.name}' (unknown candidate)")
            continue
        add_dimension(d_by_id[p.candidate], p.name, p.description, p.synonyms)
    for d in dims:                    # approved dimensions are always kept
        if d.id not in dim_name and any(x.table == d.table and x.column == d.column for x in old_dims):
            add_dimension(d, d.default_name, "", [])

    catalog = KpiCatalog(version="0.1", kpis=[], dimensions=dimensions)

    def add_kpi(m: Measure, p: ProposedKpi):
        old = next((k for k in old_kpis if k.table == m.table and _same(k.expression, m.expression)), None)
        fields = dict(name=p.name, version="1.0", description=p.description, unit=p.unit)
        if old:
            fields = dict(name=old.name, version=old.version, description=old.description, unit=old.unit,
                          filters=old.filters, population=old.population)
        else:
            twin = next((k for k in old_kpis if _same(k.expression, m.expression)), None)
            if twin:            # e.g. COUNT(DISTINCT order_id) on payments = the approved Orders
                log(f"kpi refused: {m.id} '{p.name}' has the same formula as the approved {twin.ref}")
                return
        if not NAME.match(fields["name"]) or fields["name"] in used:
            log(f"kpi refused: {m.id} '{fields['name']}' (bad or duplicate name)")
            return
        kpi = KpiDefinition(expression=m.expression, table=m.table, grain=m.grain, date_column=m.date_column,
                            allowed_dimensions=[dim_name[i] for i in m.allowed if i in dim_name], **fields)
        problem = _try(kpi, catalog, manifest, con)
        if problem:
            log(f"kpi refused: {kpi.name} does not run on the warehouse: {problem}")
            return
        used.add(kpi.name)
        catalog.kpis.append(kpi)
        terms.append(GlossaryTerm(term=kpi.name, kind="metric", synonyms=p.synonyms, definition=kpi.description))

    for p in proposal.kpis:
        if p.candidate not in m_by_id:
            log(f"kpi refused: {p.candidate} '{p.name}' (unknown candidate)")
            continue
        add_kpi(m_by_id[p.candidate], p)
    for m in measures:                # approved KPIs are always kept
        if any(k.table == m.table and _same(k.expression, m.expression) for k in old_kpis) \
                and not any(k.table == m.table and k.expression == m.expression for k in catalog.kpis):
            add_kpi(m, ProposedKpi(candidate=m.id, name=m.default_name, description="", unit=""))
    return catalog, _clean_glossary(terms, approved_glossary, log)


def _clean_glossary(terms: list[GlossaryTerm], approved_glossary: Glossary | None, log) -> Glossary:
    """Approved synonyms first; then each synonym is kept for ONE term only, otherwise Malek's
    agent could not tell which KPI "orders" or "chiffre d'affaires" means."""
    old = {t.term: t for t in (approved_glossary.terms if approved_glossary else [])}
    taken = {s.lower(): t.term for t in old.values() for s in [t.term] + t.synonyms}
    ordered = sorted(terms, key=lambda t: t.term not in old)       # approved terms claim first
    for t in ordered:
        if t.term in old:
            t.synonyms = old[t.term].synonyms + t.synonyms
            t.kind, t.definition = old[t.term].kind, old[t.term].definition
        kept = []
        for syn in t.synonyms:
            owner = taken.get(syn.lower())
            if owner not in (None, t.term):
                log(f"synonym '{syn}' removed from {t.term}: it already means {owner}")
            elif syn.lower() not in {k.lower() for k in kept}:
                kept.append(syn)
                taken[syn.lower()] = t.term
        t.synonyms = kept
    present = {t.term for t in terms}           # approved terms with no candidate ("last month"...) stay
    return Glossary(version="0.1", terms=terms + [t for t in old.values() if t.term not in present])


def _try(kpi: KpiDefinition, catalog: KpiCatalog, manifest, con) -> str | None:
    """Compile the KPI with the Analyst's own compiler (with its first dimension) and run it."""
    table = next(t for t in manifest.tables if t.name == kpi.table)
    test = KpiCatalog(version="test", kpis=[kpi], dimensions=catalog.dimensions)
    request = AnalysisRequest(question="test", metric=kpi.name, dimensions=kpi.allowed_dimensions[:1],
                              period=Period(start=table.date_min or "2000-01-01", end=table.date_max or "2100-12-31"))
    try:
        con.execute(compile_query(request, test, manifest).sql).fetchall()
    except (CompileError, duckdb.Error) as e:
        return str(e)[:200]
    return None


def propose(manifest: WarehouseManifest, warehouse: Path, *, ctx=None, use_llm: bool = True,
            approved: KpiCatalog | None = None,
            approved_glossary: Glossary | None = None) -> tuple[KpiCatalog, Glossary, str]:
    """Returns (catalog, glossary, source) where source is "llm" or "mechanical"."""
    log = (lambda msg: ctx.log("kpi_proposal_refused", msg)) if ctx else (lambda msg: None)
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        measures, dims = find_candidates(con, manifest)
        source, proposal = "mechanical", None
        if use_llm:
            prompt = load_prompt("kpi_proposer")
            try:
                proposal = chat_json(prompt.render(), _describe(measures, dims, manifest, approved), Proposal,
                                     prompt_version=prompt.ref, ctx=ctx, step="kpi_proposer")
                source = "llm"
            except (LLMUnavailable, ValidationError):
                proposal = None
        catalog, glossary = _build(proposal or _mechanical(measures, dims), measures, dims, manifest, con, log, approved, approved_glossary)
        if source == "llm" and not catalog.kpis:       # the LLM proposed nothing usable
            source = "mechanical"
            catalog, glossary = _build(_mechanical(measures, dims), measures, dims, manifest, con, log, approved, approved_glossary)
    finally:
        con.close()
    if ctx:
        ctx.log("kpi_proposal", "needs_review", evidence={
            "source": source, "candidates": len(measures), "kpis": [k.name for k in catalog.kpis],
            "dimensions": [d.name for d in catalog.dimensions]})
    return catalog, glossary, source


HEADER = ("# PROPOSAL written by analysis/kpi_proposer.py ({source}). A HUMAN MUST REVIEW IT:\n"
          "#  - check each formula, name and unit; delete what makes no sense;\n"
          "#  - add the business filters (e.g. order_status = 'delivered'): they cannot be guessed;\n"
          "#  - then copy it to {target}.\n")


def write_yaml(obj: BaseModel, path: Path, header: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(obj.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return path


if __name__ == "__main__":
    ctx = context_for("analysis", sys.argv[1] if len(sys.argv) > 1 else "dev_001")
    approved = load_yaml(KpiCatalog, ctx.inputs["catalog"]) if Path(ctx.inputs["catalog"]).exists() else None
    glossary_file = REPO_ROOT / "semantic" / "glossary.yaml"
    approved_glossary = load_yaml(Glossary, glossary_file) if glossary_file.exists() else None
    catalog, glossary, source = propose(read_output(ctx.inputs["manifest"], "etl.manifest"),
                                        ctx.inputs["warehouse"], ctx=ctx, approved=approved,
                                        approved_glossary=approved_glossary)
    out = ctx.output_dir / "proposal"
    print(f"Proposal ({source}): {len(catalog.kpis)} KPIs, {len(catalog.dimensions)} dimensions")
    for k in catalog.kpis:
        print(f"  {k.name:<22} {k.expression:<32} {k.unit:<8} by {', '.join(k.allowed_dimensions)}")
    print(write_yaml(catalog, out / "kpi_catalog_proposal.yaml", HEADER.format(source=source, target="kpi/catalog.yaml")))
    print(write_yaml(glossary, out / "glossary_proposal.yaml",
                     HEADER.format(source=source, target="semantic/glossary.yaml")))
