"""Public entrypoint specified by contracts.pipeline."""
from contracts import AgentResult, RunContext
from contracts.agent import AgentStatus
from bo2.contract_adapter import execute
from etl.agent import run as engine


def run(ctx: RunContext) -> AgentResult:
    ctx = ctx.model_copy(update={'params': {'warehouse_mode': 'dimensional', **ctx.params}})

    # ── Parquet-only mode (approved after DuckDB WDAC block) ──────────────────
    # Bypass execute() entirely: the exporter would crash on empty outputs.
    # _run_parquet_only() writes manifest/receipts/placeholder .duckdb directly.
    if ctx.params.get("etl_approval") == "parquet_only_approved":
        return engine(ctx)

    # ── Pre-probe DuckDB availability ─────────────────────────────────────────
    # We must detect WDAC blockage HERE, before execute() wraps the call.
    # execute() has a bare `except Exception` that converts ANY exception
    # (including our NEEDS_REVIEW return being rejected by the exporter) to FAILED.
    try:
        import duckdb as _ddb  # noqa: F401 -- probe only; deferred to avoid crash at import time
    except (ImportError, OSError) as _exc:
        return AgentResult(
            run_id=ctx.run_id,
            agent=ctx.agent,
            status=AgentStatus.NEEDS_REVIEW,
            outputs={},
            message=(
                "DuckDB non disponible sur cette machine (bloqué par la politique OS). "
                f"Détail : {_exc}. "
                "Appuyez sur ✅ Approuver pour continuer sans DuckDB (mode Parquet), "
                "ou ❌ Rejeter pour arrêter le pipeline."
            ),
        )

    # ── Normal DuckDB path ────────────────────────────────────────────────────
    return execute(ctx, engine)
