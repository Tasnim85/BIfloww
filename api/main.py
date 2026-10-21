"""Tasnim's API, STANDALONE (step 6): her router + /health + CORS, for her tests and the demo.

    uvicorn api.main:app --reload --port 8000          then open http://localhost:8000/docs

In the team app, only the router is used (api/router.py): same routes, same /api prefix, so
the Next.js code does not change when the team integrates.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import make_router
from api.schemas import Health, LlmInfo
from auditor import journals
from contracts.common import CONTRACTS_VERSION
from contracts.llm import LLMConfig
from contracts.pipeline import REPO_ROOT, RUNS_ROOT

PREFIX = "/api"                            # the team app must use the same prefix
DESCRIPTION = """
Tasnim's part of BIFlow, over HTTP.

* **BO4-12** — is a comparison honest? 5 checks, a justified fix, the user's decision.
* **BO3 Auditor** — SHAP explanations of anomalies, the append-only audit journal (hash chain),
  drift monitoring, and the *why?* agent (LLM + read-only tools, every number fact-checked).

Every response is a contract of `contracts/` (version in `/health`).
"""


def create_app(runs_root: Path = RUNS_ROOT, repo_root: Path = REPO_ROOT, llm=None, writer=None) -> FastAPI:
    runs_root = Path(runs_root)
    app = FastAPI(title="BIFlow API — Auditor & BO4-12", version=CONTRACTS_VERSION, description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_methods=["*"], allow_headers=["*"],
                       allow_origins=os.environ.get("BIFLOW_CORS_ORIGINS", "http://localhost:3000").split(","))
    app.include_router(make_router(runs_root, repo_root, llm, writer), prefix=PREFIX)

    @app.get("/health", response_model=Health, tags=["general"])
    def health():
        cfg = LLMConfig()
        runs = sum(1 for p in runs_root.iterdir() if p.is_dir()) if runs_root.exists() else 0
        return Health(contracts_version=CONTRACTS_VERSION, runs=runs,
                      journals=list(journals.existing(runs_root)),
                      llm=LlmInfo(provider=cfg.provider, model=cfg.model,
                                  ready=cfg.provider == "ollama" or bool(cfg.api_key())))

    return app


app = create_app()
