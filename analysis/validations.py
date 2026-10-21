"""BO3-03: prove that the number follows the approved KPI definition. No machine learning:
each check is a deterministic test that gives the same verdict on the same data, with the numbers
that justify it. The result is a list of ValidationCheck (contracts/analysis.py).

    checks = run_checks(con, q, manifest, receipts, totals)
"""
import re

import duckdb

from analysis.sql_compiler import CompiledQuery
from contracts.analysis import ValidationCheck
from contracts.warehouse import TransformationReceipts, WarehouseManifest

TOLERANCE = 0.01   # money is compared to the cent


def check_grain(q: CompiledQuery) -> ValidationCheck:
    """The KPI is defined at one grain (e.g. 'payment'); the table it runs on must have that grain."""
    ok = q.kpi.grain == q.fact.grain
    return ValidationCheck(name="grain_matches_kpi", passed=ok,
                           detail=f"{q.kpi.ref} expects grain '{q.kpi.grain}'; {q.fact.name} grain is '{q.fact.grain}'.")


def check_join_multiplicity(con: duckdb.DuckDBPyConnection, q: CompiledQuery) -> ValidationCheck:
    """A join to a dimension must not multiply fact rows: same row count before and after the joins."""
    before = con.execute(q.count_sql).fetchone()[0]
    after = con.execute(q.joined_count_sql).fetchone()[0]
    joined = " -> ".join([q.fact.name] + [j.table for j in q.joins]) or q.fact.name
    if after == before:
        detail = f"{q.fact.name} has {before} rows before and after the joins ({joined}): no row was duplicated."
    elif after > before:
        detail = (f"{q.fact.name} has {before} rows but {after} after the joins ({joined}): "
                  f"{after - before} rows were duplicated, so the KPI would be counted more than once.")
    else:
        detail = f"{q.fact.name} has {before} rows but {after} after the joins ({joined}): {before - after} rows were lost."
    return ValidationCheck(name="join_multiplicity", passed=after == before, detail=detail)


def check_reference_value(con: duckdb.DuckDBPyConnection, q: CompiledQuery,
                          totals: dict[str, float]) -> ValidationCheck | None:
    """Reference test: the breakdown must add up to the KPI computed on the fact table alone.
    Only meaningful for additive KPIs (SUM) without request filters: returns None otherwise."""
    # additive = ONE plain SUM(...): "SUM(a) / COUNT(DISTINCT b)" (a ratio) does not add up by group
    if q.has_request_filters or not re.fullmatch(r"SUM\([^()]*\)", q.kpi.expression.strip(), re.I):
        return None
    reference = dict(con.execute(q.reference_sql).fetchall())
    gaps = {p: round(totals.get(p, 0.0) - v, 2) for p, v in reference.items()}
    ok = all(abs(g) <= TOLERANCE for g in gaps.values())
    parts = ", ".join(f"{p}: {totals.get(p, 0.0):,.2f} vs reference {v:,.2f}" for p, v in reference.items())
    return ValidationCheck(name="reference_value", passed=ok,
                           detail=f"Breakdown total vs {q.kpi.expression} on {q.fact.name} alone: {parts}.")


def check_etl_receipt(q: CompiledQuery, manifest: WarehouseManifest,
                      receipts: TransformationReceipts) -> ValidationCheck:
    """The ETL receipt of the fact table must confirm its grain and that its own joins did not fan out."""
    receipt = next((r for r in receipts.receipts if r.output_table == q.fact.name), None)
    if receipt is None:
        return ValidationCheck(name="etl_receipt", passed=False,
                               detail=f"No ETL receipt for {q.fact.name}: its construction cannot be verified.")
    problems = []
    if receipt.grain != q.kpi.grain:
        problems.append(f"receipt grain '{receipt.grain}' differs from KPI grain '{q.kpi.grain}'")
    if receipt.rows_after > receipt.rows_before:
        problems.append(f"the ETL produced {receipt.rows_after} rows from {receipt.rows_before} "
                        f"(joins on {', '.join(receipt.join_keys)} duplicated rows)")
    if receipt.rows_after != q.fact.row_count:
        problems.append(f"receipt says {receipt.rows_after} rows, manifest says {q.fact.row_count}")
    detail = ("; ".join(problems) + ".") if problems else (
        f"{q.fact.name} was built from {receipt.rows_before} rows of {receipt.source_tables[0]} into "
        f"{receipt.rows_after} rows at grain '{receipt.grain}': no fan-out in the ETL.")
    return ValidationCheck(name="etl_receipt", passed=not problems, detail=detail)


def run_checks(con: duckdb.DuckDBPyConnection, q: CompiledQuery, manifest: WarehouseManifest,
               receipts: TransformationReceipts, totals: dict[str, float]) -> list[ValidationCheck]:
    checks = [check_grain(q), check_join_multiplicity(con, q),
              check_reference_value(con, q, totals), check_etl_receipt(q, manifest, receipts)]
    return [c for c in checks if c is not None]
