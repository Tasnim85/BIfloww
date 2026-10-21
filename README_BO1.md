# BIFlow — BO1/Samar+Malek Branch

**Repository:** `https://github.com/Tasnim85/BIfloww.git`  
**Branch:** `BO1/Samar+Malek`  
**Team:** Samar (Orchestrator + App) · Malek (Intake + Semantic)

---

## What Was Built

### Samar — DAG Orchestrator & App (BO1-01)

| File | Description |
|---|---|
| `orchestrator/dag_runner.py` | DAG runner using `graphlib.TopologicalSorter` + `ThreadPoolExecutor` |
| `orchestrator/task_store.py` | SQLite task state persistence (PENDING/RUNNING/SUCCESS/FAILED/SKIPPED) |
| `app/app.py` | Streamlit shell: upload → pipeline progress → dashboard |
| `app/upload.py` | Step `upload` entrypoint: write `Upload` contract |
| `app/dashboard.py` | Step `dashboard` entrypoint: automatic chart selection |

### Malek — Semantic Detection (Step 1a + BO1-06 Phase 1)

| File | Description |
|---|---|
| `intake/column_types.py` | Step `column_types` entrypoint: rule-based classification |
| `intake/similarity.py` | Step `similarity` entrypoint: Jaccard column-name matching |
| `semantic/request.py` | Step `request` entrypoint: keyword-based NL→AnalysisRequest |
| `intake/semantic_detection/` | Full semantic detection module (see its README) |

---

## Run the App

```bash
# Install dependencies
pip install streamlit pydantic pyyaml pandas pyarrow

# Launch
streamlit run app/app.py
```

## Run Tests

```bash
# Malek's semantic detection tests
pytest intake/semantic_detection/tests/ -v

# Contract regression suite (team-wide)
python -m contracts.check_contracts
```

## Anti-Conflict Guarantees

This branch ONLY writes to these folders:
- `intake/` — Malek's column classification
- `semantic/` — Malek's request understanding  
- `orchestrator/` — Samar's DAG runner
- `app/` — Samar's Streamlit app
- `contracts/proposals/` — new contracts (proposals, not modifying existing)
- `data/sample/` — shared Olist sample data

The following folders are **never touched**:
`privacy/`, `profiling/`, `cleaning/`, `etl/`, `kpi/`, `analysis/`, `comparisons/`, `auditor/`
