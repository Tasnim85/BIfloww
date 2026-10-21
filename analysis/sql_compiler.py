"""Turn (request + KPI definition) into SQL. The SQL is BUILT from the catalog, never written by hand
or by an LLM: that is what guarantees the number follows the approved formula (BO3-03).

    q = compile_query(request, catalog, manifest)
    q.sql            # the query whose rows go to result.parquet: <dimensions>, period, value
    q.reference_sql  # the same KPI on the fact table alone, no join and no request filter:
                     # used by the reference test
"""
import re
from dataclasses import dataclass, field

from contracts.semantic import AnalysisRequest, KpiCatalog, KpiDefinition
from contracts.warehouse import TableKind, WarehouseManifest, WarehouseTable

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A request filter must look like:  <dimension> <op> <literal>   e.g.  customer_state = 'SP'
SIMPLE_FILTER = re.compile(r"^\s*(\w+)\s*(=|!=|<>|<=|>=|<|>|IN)\s*('[^';]*'|\d+(\.\d+)?|\(('[^';]*'\s*,?\s*)+\))\s*$", re.I)


class CompileError(ValueError):
    """The request cannot be computed with the approved definition (unknown KPI, forbidden dimension...)."""


@dataclass
class Join:
    table: str
    alias: str
    on: str                                  # SQL condition, e.g. "f.customer_id = d1.customer_id"


@dataclass
class CompiledQuery:
    kpi: KpiDefinition
    sql: str
    reference_sql: str
    fact: WarehouseTable
    joins: list[Join] = field(default_factory=list)
    dimension_columns: list[str] = field(default_factory=list)   # output column names, in order
    has_request_filters: bool = False
    count_sql: str = ""           # rows of the fact table that enter the KPI (no join)
    joined_count_sql: str = ""    # the same rows AFTER the dimension joins: must be equal (BO3-03)


def _table(manifest: WarehouseManifest, name: str) -> WarehouseTable:
    for t in manifest.tables:
        if t.name == name:
            return t
    raise CompileError(f"Table '{name}' is not in the warehouse manifest.")


def _check_date(d: str) -> str:
    if not ISO_DATE.match(d):
        raise CompileError(f"'{d}' is not an ISO date (YYYY-MM-DD).")
    return d


def find_join_path(manifest: WarehouseManifest, fact: WarehouseTable, target: str,
                   date_column: str) -> list[tuple[WarehouseTable, WarehouseTable, str]]:
    """Shortest chain of many-to-one joins from the fact table to `target` (breadth-first search).

    A table A can join a dimension B when B has a one-column primary key that is also a column of A
    (e.g. fact_payments.customer_id -> dim_customer.customer_id), or when B is a calendar (grain "day")
    and A is the fact table (A.<date_column> -> B.date). Returns [(A, B, "join condition"), ...].
    """
    if target == fact.name:
        return []
    tables = {t.name: t for t in manifest.tables}
    if target not in tables:
        raise CompileError(f"Table '{target}' is not in the warehouse manifest.")
    paths, queue = {fact.name: []}, [fact]
    while queue:
        a = queue.pop(0)
        for b in manifest.tables:
            if b.name in paths or b.kind != TableKind.DIMENSION or len(b.primary_key) != 1:
                continue
            key = b.primary_key[0]
            if key in a.columns:
                on = "{a}.%s = {b}.%s" % (key, key)
            elif b.grain == "day" and a is fact and date_column in a.columns:
                on = "{a}.%s = {b}.%s" % (date_column, key)
            else:
                continue
            paths[b.name] = paths[a.name] + [(a, b, on)]
            if b.name == target:
                return paths[target]
            queue.append(b)
    raise CompileError(f"No join path from {fact.name} to {target} in the manifest.")


def compile_query(request: AnalysisRequest, catalog: KpiCatalog, manifest: WarehouseManifest) -> CompiledQuery:
    try:
        kpi = catalog.kpi(request.metric)
    except StopIteration:
        raise CompileError(f"KPI '{request.metric}' is not in the catalog.") from None
    fact = _table(manifest, kpi.table)

    # 1. Dimensions: only those the KPI allows. The join path to each dimension table is
    #    FOUND in the manifest (star: 1 hop, snowflake: several hops, constellation: same rules).
    dims = {d.name: d for d in catalog.dimensions}
    joins, select_dims, column_of = [], [], {}
    alias_of = {fact.name: "f"}
    for name in request.dimensions:
        if name not in kpi.allowed_dimensions:
            raise CompileError(f"Dimension '{name}' is not allowed for {kpi.ref} "
                               f"(allowed: {', '.join(kpi.allowed_dimensions)}).")
        dim = dims[name]
        for parent, child, on in find_join_path(manifest, fact, dim.table, kpi.date_column):
            if child.name not in alias_of:
                alias_of[child.name] = f"d{len(alias_of)}"
                joins.append(Join(child.name, alias_of[child.name],
                                  on.format(a=alias_of[parent.name], b=alias_of[child.name])))
        expr = f"{alias_of[dim.table]}.{dim.column}"
        select_dims.append(f"{expr} AS {name}")
        column_of[name] = expr

    # 2. Filters: the KPI's approved filters first, then the request's, checked one by one.
    where = [f"f.{f}" if not f.startswith("f.") else f for f in kpi.filters]
    request_filters = []
    for flt in request.filters:
        m = SIMPLE_FILTER.match(flt)
        if not m or m.group(1) not in column_of and m.group(1) not in kpi.allowed_dimensions:
            raise CompileError(f"Filter '{flt}' is not a simple filter on an allowed dimension.")
        if m.group(1) not in column_of:   # filter on a dimension not in the breakdown: join it too
            raise CompileError(f"Filter '{flt}': add '{m.group(1)}' to the dimensions to filter on it.")
        request_filters.append(flt.replace(m.group(1), column_of[m.group(1)], 1))

    # 3. Periods: 'current' = request.period, 'previous' = compare_to.
    date = f"f.{kpi.date_column}"
    cur = (_check_date(request.period.start), _check_date(request.period.end))
    period_case = f"'current'"
    period_where = f"{date} BETWEEN '{cur[0]}' AND '{cur[1]}'"
    if request.compare_to:
        prev = (_check_date(request.compare_to.start), _check_date(request.compare_to.end))
        period_case = f"CASE WHEN {date} BETWEEN '{cur[0]}' AND '{cur[1]}' THEN 'current' ELSE 'previous' END"
        period_where = f"({period_where} OR {date} BETWEEN '{prev[0]}' AND '{prev[1]}')"
    where.append(period_where)

    join_sql = "".join(f" JOIN {j.table} {j.alias} ON {j.on}" for j in joins)
    where_sql = " AND ".join(where + request_filters)
    reference_where = " AND ".join(where)   # no request filter: they need the dimension joins
    expression = re.sub(r"\b(?<!\.)(" + "|".join(map(re.escape, fact.columns)) + r")\b", r"f.\1", kpi.expression)
    group = ", ".join(str(i + 1) for i in range(len(select_dims) + 1))
    sql = (f"SELECT {', '.join(select_dims + [f'{period_case} AS period'])}, {expression} AS value "
           f"FROM {fact.name} f{join_sql} WHERE {where_sql} GROUP BY {group} ORDER BY {group}")
    reference_sql = (f"SELECT {period_case} AS period, {expression} AS value "
                     f"FROM {fact.name} f WHERE {reference_where} GROUP BY 1 ORDER BY 1")
    return CompiledQuery(kpi=kpi, sql=sql, reference_sql=reference_sql, fact=fact, joins=joins,
                         dimension_columns=list(request.dimensions),
                         has_request_filters=bool(request_filters),
                         count_sql=f"SELECT COUNT(*) FROM {fact.name} f WHERE {reference_where}",
                         joined_count_sql=f"SELECT COUNT(*) FROM {fact.name} f{join_sql} WHERE {reference_where}")
