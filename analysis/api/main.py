"""Rabeb's API, STANDALONE: her router + /health + CORS, for her tests and the demo.

    uvicorn analysis.api.main:app --reload --port 8001        then open http://localhost:8001/docs

In the team app only the router is used (analysis/api/router.py), with the same /api prefix,
so the Next.js code does not change when the team integrates.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analysis.api.router import make_router
from analysis.api.schemas import Health, LlmInfo
from contracts.audit import DEFAULT_JOURNAL
from contracts.common import CONTRACTS_VERSION
from contracts.llm import LLMConfig
from contracts.pipeline import REPO_ROOT, RUNS_ROOT
from contracts.semantic import KpiCatalog, load_yaml

PREFIX = "/api"                            # the team app must use the same prefix
DESCRIPTION = """
Rabeb's part of BIFlow, over HTTP.

* **Analyst (step 5, BO3-03)**: the KPI computed with SQL built from the approved catalog, the 4
  validation checks, and insights written by an LLM agent (every number fact-checked).
* **KPI catalog**: the approved KPIs and the glossary, and a KPI computed live with its checks.
* **KPI proposer**: a draft catalog for any warehouse, reviewed by a human before use.

Every response is a contract of `contracts/` (version in `/health`).
"""


def create_app(runs_root: Path = RUNS_ROOT, repo_root: Path = REPO_ROOT,
               journal: Path = DEFAULT_JOURNAL) -> FastAPI:
    app = FastAPI(title="BIFlow API — Analyst & KPI catalog", version=CONTRACTS_VERSION, description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_methods=["*"], allow_headers=["*"],
                       allow_origins=os.environ.get("BIFLOW_CORS_ORIGINS", "http://localhost:3000").split(","))
    app.include_router(make_router(runs_root, repo_root, journal), prefix=PREFIX)

    @app.get("/health", response_model=Health, tags=["general"])
    def health():
        cfg = LLMConfig()
        catalog = load_yaml(KpiCatalog, Path(repo_root) / "kpi" / "catalog.yaml")
        return Health(contracts_version=CONTRACTS_VERSION, catalog_version=catalog.version, kpis=len(catalog.kpis),
                      llm=LlmInfo(provider=cfg.provider, model=cfg.model,
                                  ready=cfg.provider == "ollama" or bool(cfg.api_key())))

    return app


app = create_app()
