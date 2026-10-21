# BIFlow — Intelligent Multi-Agent BI Platform

BIFlow is an automated Business Intelligence pipeline powered by specialized AI agents and governed by strictly typed Pydantic contracts.

This branch (`BO1/Samar+Malek`) delivers:
- **Step 1a (Malek):** Semantic Foundation, Taxonomy Design & Column Classification (`intake/semantic_detection/`, `intake/column_types.py`).
- **BO1-01 (Samar):** DAG Orchestrator with SQLite state store, failure resume, and unified Streamlit UI (`orchestrator/`, `app/`).
- **BO1-06 Phase 1 (Malek):** Dataset similarity detection baseline (`intake/similarity.py`).
- **BO4-06 Phase 1 (Malek):** Natural language request understanding (`semantic/request.py`).

---

## 1. Architecture Overview

BIFlow processes data through a directed acyclic graph (DAG) defined in `contracts.pipeline`:

```
upload
  ├──> similarity (BO1-06)
  └──> column_types (Step 1a) ──> pii ──> profiling ──> cleaning ──> etl ──> analysis ──> dashboard
  └──> request (BO4-06) ─────────────────────────────────────────────┘
```

Every agent communicates via standardized data contracts located in `contracts/` and records operations in an immutable SQLite audit journal (`runs/audit.db`).

---

## 2. Installation

Prerequisites: Python 3.10+ (tested on Python 3.13).

```bash
# Clone the repository and checkout branch
git clone https://github.com/Tasnim85/BIfloww.git
cd BIfloww
git checkout BO1/Samar+Malek

# Create and activate a virtual environment
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

---

## 3. Running Automated Tests

Run the full automated test suite (unit tests, golden dataset tests, contract checks):

```bash
# Run all pytest suites
python -m pytest -v

# Verify shared data contracts & DAG validity
python -m contracts.check_contracts
```

---

## 4. Running the Semantic Foundation Notebook

The interactive Jupyter notebook for Step 1a is located at:
`intake/semantic_detection/notebooks/01_semantic_foundation.ipynb`

To launch Jupyter and execute the notebook:

```bash
jupyter notebook intake/semantic_detection/notebooks/01_semantic_foundation.ipynb
```

Or execute headless via `nbconvert`:
```bash
jupyter nbconvert --to notebook --execute intake/semantic_detection/notebooks/01_semantic_foundation.ipynb --output executed_01.ipynb
```

---

## 5. Running the Pipeline & Web UI

### Command-line execution:
```bash
python -m orchestrator.dag_runner --run-id demo_run
```

### Streamlit Web Application:
```bash
streamlit run app/app.py
```

---

## 6. Documentation Index

- [Taxonomy Specification](docs/SEMANTIC_TAXONOMY.md): 10 semantic groups, 65+ types, privacy hints.
- [Data Contracts Reference](docs/DATA_CONTRACTS.md): Pydantic v2 schemas and bridge to `contracts.intake`.
- [Integration Guide](docs/INTEGRATION_GUIDE.md): DAG execution flow and team contract boundaries.
- [Contract Change Proposal](docs/CONTRACT_CHANGE_PROPOSAL.md): Proposed extensions and privacy vocabulary alignment.
- [Validation Report](VALIDATION_REPORT.md): Automated taxonomy validation results.
