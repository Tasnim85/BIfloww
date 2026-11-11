# BIFlow / Askboard

**An autonomous multi-agent Business Intelligence system.**
Drop CSV files, ask a question in plain language, and get a checked, explained and audited dashboard, without a data engineer in the loop.

*BIFlow* is the multi-agent engine (Python). *Askboard* is the web application built on top of it (FastAPI + Next.js).
Integrated project (PI), Data Science, class 5DS3, ESPRIT, academic year 2026-2027.

---

## Table of contents

1. [What it does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [Repository layout](#3-repository-layout)
4. [Requirements](#4-requirements)
5. [Quick start](#5-quick-start)
6. [Configuration](#6-configuration)
7. [Language models used](#7-language-models-used)
8. [Using the application](#8-using-the-application)
9. [HTTP API](#9-http-api)
10. [Tests and checks](#10-tests-and-checks)
11. [Documentation index](#11-documentation-index)
12. [Security](#12-security)
13. [Known limitations](#13-known-limitations)
14. [Team](#14-team)

---

## 1. What it does

Moving from raw tabular data to a trusted dashboard is slow, error-prone and opaque. BIFlow automates the whole chain with specialised agents, under one rule: **decisions are deterministic, and language models only propose or explain.** Anything that changes the data (PII types, cleaning rules, warehouse schema) waits for a named human approval, and every generated sentence is fact-checked against the data before it is shown.

The system serves four business objectives (BO):

| Objective | Goal | Main mechanisms |
|---|---|---|
| **BO1** Time-to-insight | Shorten the cycle from raw data to a usable insight | DAG orchestrator, parallel execution, resume after a failure or a review |
| **BO2** Governance | Remove human error from cleaning, schema discovery and modelling | Versioned cleaning playbooks, PII masking, reviewed warehouse design, contract checks |
| **BO3** Explainability and auditability | A rationale and a log for every transformation, KPI and insight | SHAP explanations, hash-chained audit journal, drift monitor, evidence-based "why?" agent |
| **BO4** Democratisation | Dashboards for managers without engineering help | Natural-language questions, automatic chart choice, misleading-comparison checks, web app |

BIFlow is designed for any tabular dataset: no agent is written for a particular schema. It was developed and tested on the public [Olist Brazilian e-commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (8 tables, about 556,000 rows), plus a small clinic dataset.

## 2. Architecture

An **Orchestrator** runs a directed acyclic graph (DAG) of **13 steps** carried out by **six specialised agents**. Steps never call each other: they exchange files validated by shared Pydantic contracts (`contracts/`, version 1.6), so each agent can be developed and tested alone.

```
upload ──► similarity ──► column_types ──► pii ──► profiling ──► cleaning ──► etl ──► request
                                                                                │
                              analysis ◄────────────────────────────────────────┘
                                 │
                                 ├──► comparisons ──► dashboard ──► lineage ──► auditor
```

| Agent | Steps | What it does | Directories |
|---|---|---|---|
| **Orchestrator** | `upload` | Receives the files and the question; builds the DAG, runs independent steps in parallel, stops at human reviews and resumes | `orchestrator/`, `intake/`, `contracts/` |
| **Data Profiler, Quality & Cleaning** | `similarity`, `column_types`, `pii`, `profiling`, `cleaning` | Recognises known datasets, types every column, masks personal data (HMAC-SHA256), profiles quality and detects anomalies (Isolation Forest), applies versioned cleaning playbooks | `intake/`, `privacy/`, `profiling/`, `cleaning/`, `bo2/` |
| **ETL / Data Engineering** | `etl`, `lineage` | Designs and builds the DuckDB warehouse (star, snowflake or constellation) after a human approval; records a lineage graph from each KPI to its sources | `etl/` |
| **BI Semantic & KPI** | `request` | Turns the question into a structured request using the business glossary and the KPI catalogue; drafts a KPI catalogue for a new dataset | `semantic/`, `kpi/` |
| **BI Analyst** | `analysis` | Compiles SQL from the KPI catalogue (never written by an LLM), runs four validation checks on every result, writes fact-checked insights | `analysis/` |
| **Dashboard Generator** | `comparisons`, `dashboard` | Detects misleading comparisons (five checks, proposed fixes, user decision) and chooses the right chart with explicit scoring rules | `comparisons/`, `dashboard_ai/` |
| **BI Auditor / XAI** | `auditor` | SHAP explanations in natural language, append-only hash-chained journal, drift monitoring, and a "why?" agent that answers only from evidence | `auditor/` |

Design principles:

1. **Deterministic decisions, LLMs for proposals and words.** Thresholds live in versioned rule files.
2. **Human approval for anything that changes the data.** The reviewer's name and the time are recorded.
3. **Contracts between agents.** Agents never import each other's code.
4. **Fact-checking of generated text.** A sentence with a number that is not in the facts is refused and replaced by a template.
5. **Everything is journaled.** Each decision is appended to a journal whose entries are chained by SHA-256 hashes; SQLite triggers refuse any `UPDATE` or `DELETE`.

## 3. Repository layout

```
contracts/        shared Pydantic contracts, DAG definition, LLM client, prompt loader, fact checker
orchestrator/     DAG runner, task store (SQLite), barriers, resume
intake/           upload, dataset similarity, semantic column typing
privacy/          PII detection and masking
profiling/        quality profile, anomaly model
cleaning/         versioned cleaning playbooks, LLM-proposed rules
bo2/              shared helpers of the data-governance agents (local LLM client, models)
etl/              warehouse design, build, lineage
semantic/         question understanding, business glossary
kpi/              KPI catalogue
analysis/         KPI compiler, validation checks, insights
comparisons/      misleading-comparison checks and fixes
dashboard_ai/     chart choice and visual rules
auditor/          SHAP, audit journal, drift monitor, "why?" agent
prompts/          versioned system prompts (YAML)
api/              FastAPI back end
web/              Next.js web application (Askboard)
app/              first Streamlit prototype (kept for reference)
tools/            integration scripts (full run with reviews, test double for Ollama)
tests/            automated tests
data/sample/      small synthetic Olist-like sample (500 orders)
docs/             contracts, taxonomy and integration documents
```

## 4. Requirements

- **Python 3.11+** (tested on 3.13)
- **Node.js 22 or 24** for the web application
- **Ollama with `llama3`** for the local steps (PII, cleaning rules, warehouse design). Without Ollama you can still try the pipeline with the test double described in [section 10](#10-tests-and-checks).
- **A Groq API key** (free tier) for the cloud steps (insights, KPI proposal, comparison summary, "why?" agent). Without it these steps fall back to deterministic templates.

## 5. Quick start

### 5.1 Python back end

```bash
git clone https://github.com/Tasnim85/BIfloww.git
cd BIfloww

python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows (cmd)
.venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-bo2.txt -r requirements-app.txt
pip install shap joblib scipy fastapi "uvicorn[standard]" httpx
```

Create a `.env` file at the repository root (it is ignored by git and must never be committed):

```
GROQ_API_KEY=gsk_...
BIFLOW_LLM_MODEL=openai/gpt-oss-120b
```

Set the secret used to pseudonymise personal data (32 characters or more), then start Ollama in another terminal:

```bash
# Linux / macOS
export BO2_PII_SECRET="<at least 32 characters>"
# Windows (cmd)
set BO2_PII_SECRET=<at least 32 characters>

ollama pull llama3
```

Start the API:

```bash
uvicorn api.main:app --port 8000
```

Interactive documentation: <http://localhost:8000/docs>. Health check: <http://localhost:8000/health> (contract version, LLM status, presence of the PII secret).

### 5.2 Web application

```bash
cd web
npm install
cp .env.example .env.local        # Windows: copy .env.example .env.local
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

Paste the generated value in `.env.local` as `NEXTAUTH_SECRET=`, then:

```bash
npm run dev
```

Open <http://localhost:3000> (English by default; French/English and light/dark are in the top-right corner). Google sign-in, reCAPTCHA and the welcome email are optional in development; the commented template `web/.env.example` explains each key.

Run the API (section 5.1) and the web app in two terminals.

### 5.3 First analysis

1. Create an account and sign in.
2. Click **New analysis**, upload CSV files (or pick the Olist showcase), and type a question, for example *"Revenue by customer state, August 2018 vs July 2018"*.
3. Follow the pipeline rail. When a step needs a person (PII types, cleaning rules, warehouse schema), a review card appears: approve it, and the same run resumes.
4. If the comparison is misleading, choose between the comparison as asked and the proposed correction. Your choice is journaled with your name.
5. Open the dashboard, the auditor pages (explanations, journal, drift) and ask **"Why?"** about any decision.

The full Olist dataset is available on [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce). `data/sample/` contains a small synthetic sample for quick tests.

## 6. Configuration

### Back end (environment variables or root `.env`)

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | API key of the cloud LLM provider (default provider: Groq) |
| `BIFLOW_LLM_PROVIDER` | `groq` (default), `gemini`, `openrouter` or `ollama` |
| `BIFLOW_LLM_MODEL` | Model name; the project uses `openai/gpt-oss-120b` on Groq |
| `BIFLOW_LLM_BASE_URL` | Override the provider URL |
| `BO2_PII_SECRET` | Secret (32+ characters) for HMAC pseudonymisation of personal data |
| `OLLAMA_TIMEOUT` | Seconds to wait for the local model (use `600` on a machine without a GPU) |
| `BIFLOW_JOURNALS` | Visible journals, e.g. `real,ui` to hide demo journals in production |
| `BIFLOW_CORS_ORIGINS` | Allowed origins of the API (default `http://localhost:3000`) |
| `BIFLOW_CLEANING_MODE` | Set to `generate` to force the LLM-proposed cleaning rules and their approval (demo switch) |
| `NEO4J_PASSWORD` | Only if the lineage graph uses the optional Neo4j backend (the default JSON backend needs nothing) |

To list the models your provider offers: `python -m contracts.llm --models`.

### Web (`web/.env.local`)

`BACKEND_URL` (where the API runs), `NEXTAUTH_URL`, `NEXTAUTH_SECRET`, `DATABASE_PATH`, and the optional `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, `NEXT_PUBLIC_RECAPTCHA_SITE_KEY`/`RECAPTCHA_SECRET_KEY`, `SMTP_*` and `MAIL_FROM`. The commented template is `web/.env.example`.

## 7. Language models used

All LLM calls go through one client (`contracts/llm.py`): temperature 0, fixed seed, structured output validated by a Pydantic schema, and every call is journaled with the model, the prompt version and the SHA-256 of the prompt and of the output.

| Agent | LLM role | Model | Guardrail |
|---|---|---|---|
| Data Profiler, Quality & Cleaning | Classify PII; propose cleaning rules | Llama 3 (`llama3:latest`), local via Ollama | Deterministic masking; a proposal never authorises itself; named approval |
| ETL / Data Engineering | Propose a dimensional design | Llama 3, local via Ollama | Picks from a fixed list, never writes SQL; named approval of a fingerprinted proposal |
| BI Semantic & KPI | Draft a KPI catalogue for a new dataset | gpt-oss-120b via Groq | Human review before use |
| BI Analyst | Choose breakdowns; write insights | gpt-oss-120b via Groq | Tool is Python; sentences fact-checked; deterministic fallback |
| Dashboard Generator | Rephrase the comparison summary | gpt-oss-120b via Groq | Fact check; template kept if refused |
| BI Auditor / XAI | Investigate and write answers to "why?" | gpt-oss-120b via Groq | Read-only tools; deterministic verifier; template fallback |

A sentence-embedding model (`all-MiniLM-L6-v2`, Sentence-Transformers) is also used locally for dataset similarity, column typing and question matching. It generates no text.

All prompts are **system prompts** kept in `prompts/` as versioned YAML files with a changelog. If the provider is unavailable or rate limited (HTTP 429), the agents fall back to deterministic templates and the evidence from the journal is still shown.

## 8. Using the application

- **Run view.** A rail shows the 13 steps grouped by agent, with the real status of each, updated live. Clicking a step opens an inspector with what that agent produced.
- **Review cards.** PII types, LLM-proposed cleaning rules and the warehouse schema wait for a named reviewer. Each approval shows who approved it and when; the name comes from the server session and cannot be forged from the browser.
- **Comparison check.** A comparison that mixes a complete period with an incomplete one is blocked, with a justified correction. Example from the Olist data: August 2018 versus July 2018 reads -4.1% as asked, but August is complete for only 23 of 31 days; on the same 23 days the change is +34.6%.
- **Auditor.** Anomaly explanations (SHAP, in a plain sentence), the hash-chained journal with an integrity check, drift monitoring across runs, and the "why?" agent.
- **Languages and themes.** English and French, light and dark.

## 9. HTTP API

All routes are under the `/api` prefix (except `/health`). The OpenAPI description is exported with `python -m api.export_openapi`, and the TypeScript types of the web app are generated from it (`npm run types:api` in `web/`), so a change in the back end breaks the front-end build instead of failing at run time.

| Group | Routes |
|---|---|
| Pipeline and uploads | `POST /uploads`, `GET /runs/{id}/progress`, `POST /runs/{id}/review`, `GET /runs/{id}/pipeline`, `GET /runs/{id}/charts`, `POST /parse` |
| Runs and datasets | `GET /runs`, `GET /runs/{id}`, `GET /datasets` |
| Comparisons and dashboard | `GET /runs/{id}/comparison`, `POST /runs/{id}/comparison/decision`, `POST /comparisons`, `GET /runs/{id}/dashboard` |
| Auditor | `GET /runs/{id}/explanations`, `GET /runs/{id}/explanations/{row_key}`, `POST /runs/{id}/why`, `GET /runs/{id}/journal`, `GET /journals`, `GET /journals/{id}/entries`, `GET /journals/{id}/verify`, `GET /runs/{id}/drift`, `GET /drift` |
| Health | `GET /health` |

Open `/docs` on the running API to try each route. The browser never calls the Python API directly: the Next.js server proxy requires a session, allows only a list of routes and checks ownership of each run.

## 10. Tests and checks

```bash
python -m contracts.check_contracts     # contracts, DAG, prompts, languages, journal
python -m pytest tests -q               # unit and integration tests (more than 600)
```

For the web application (from `web/`):

```bash
npm run typecheck
npm run build
```

**Running the full pipeline without Ollama.** `tools/integration/fake_ollama.py` is a local test double that imitates plausible `llama3` answers (`FAKE_SCENARIO=ideal`, `orders_fact`, `star`, `drop_links`, `drop_payment_link`, `pii_unsure`). It is only for checking that data flows between agents, never for a demo. Full run with the human reviews:

```bash
python -m tools.integration.run_with_reviews integ_001
python -m tools.integration.check_warehouse integ_001      # is every KPI computable?
```

Runs are written to `runs/<run_id>/`, one sub-folder per step, and are ignored by git.

## 11. Documentation index

- [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md): Pydantic v2 schemas
- [`docs/SEMANTIC_TAXONOMY.md`](docs/SEMANTIC_TAXONOMY.md): semantic column types and privacy hints
- [`docs/INTEGRATION_GUIDE.md`](docs/INTEGRATION_GUIDE.md): DAG execution flow and team boundaries
- [`INTEGRATION.md`](INTEGRATION.md): how the agents were integrated, and the fixes made
- [`VALIDATION_REPORT.md`](VALIDATION_REPORT.md): validation of the semantic detection

## 12. Security

- Secrets (`.env`, `web/.env.local`) are never committed; `runs/`, `*.db` and `*.duckdb` are ignored by git.
- Personal data is pseudonymised with HMAC-SHA256 before the later steps see it.
- The journal is append-only: SQLite triggers refuse `UPDATE` and `DELETE`, and each entry is chained to the previous one by a SHA-256 hash. `GET /journals/{id}/verify` recomputes the chain and reports the first broken entry.
- Web: passwords hashed with bcrypt, rate limits on sign-in and sign-up, server-side reCAPTCHA, signed session cookies, route allow-list and ownership checks in the proxy, security headers.

## 13. Known limitations

- Single machine: SQLite and DuckDB files, at most two concurrent pipelines. A production version needs a job queue, a server database and object storage.
- The KPI catalogue and glossary are written by hand for Olist; the KPI proposer drafts them for a new dataset, but a person must review them.
- Anomaly detection covers one table (payments) and three numeric features.
- Thresholds (comparison checks, dashboard rules, PSI limits) are expert judgement and versioned, not learned.
- The "why?" and insight agents depend on an external LLM provider; the free tier is rate limited, and the template fallback is less natural.
- A person with write access to the journal file could rebuild the whole hash chain; publishing the latest hash to an external place would close this gap.
- The personas were not validated with a study of real users.

## 14. Team

Tasnim Ben Hassine, Rabeb Bougatef, Ikbel Hamdi, Ahmed Fekih, Samar Omrani, Mohamed Melek Hammami.

Generative AI tools (Claude, Anthropic) were used as an assistant for parts of the code, the documentation and the project report, and the team reviewed the result. The system itself uses language models by design, as described in section 7.
