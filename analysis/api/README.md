# API BIFlow : partie de Rabeb (Analyst, catalogue des KPI)

L'API expose l'Analyst (étape 5, BO3-03), le catalogue des KPI et le proposeur de KPI en HTTP, pour l'application Next.js.

Elle suit exactement l'organisation de l'API de Tasnim (`api/`) :
- elle ne contient **aucune logique métier** ;
- elle appelle les mêmes fonctions que les pages Streamlit ;
- elle renvoie les contrats tels quels.

## Lancer

```cmd
pip install fastapi "uvicorn[standard]" httpx
uvicorn analysis.api.main:app --reload --port 8001
```

La documentation interactive est sur http://localhost:8001/docs. Chaque route peut y être testée avec « Try it out ».

Toutes les routes commencent par **`/api`**, sauf `/health`.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `router.py` | **toutes les routes**, sous forme d'`APIRouter` : c'est ce que l'équipe intègre |
| `main.py` | l'app **autonome** (router + `/health` + CORS), pour les tests et la démo |
| `schemas.py` | les corps de requête et de réponse qui ne sont pas déjà des contrats |
| `export_openapi.py` | écrit `openapi.json`, d'où Next.js tire ses types TypeScript |

## Intégration dans l'API de l'équipe (une ligne de plus)

```python
from fastapi import FastAPI
from api.router import router as tasnim_router
from analysis.api.router import router as analyst_router

app = FastAPI(title="BIFlow")
app.include_router(tasnim_router, prefix="/api")
app.include_router(analyst_router, prefix="/api")      # même préfixe : Next.js ne change pas
```

Aucune route ne se chevauche avec celles de Tasnim. Les siennes sont `/runs`, `/runs/{id}`, `/comparison`, `/dashboard`, `/explanations`, `/why`, `/journal`, `/drift`, `/comparisons`, `/journals` et `/datasets`.

## Les routes

| Route | Rôle |
|---|---|
| `GET /health` (app autonome) | version des contrats et du catalogue, nombre de KPI, LLM prêt ou non |
| `POST /api/runs/{run_id}/analysis` | **lance l'Analyst** sur un run (`{"llm": true}` ou `false`) : renvoie le statut et le résultat |
| `GET /api/runs/{run_id}/analysis` | le résultat : valeur, comparaison, version du KPI, SQL, 4 contrôles BO3-03, insights |
| `GET /api/runs/{run_id}/analysis/rows` | `result.parquet` en JSON (dimensions, `period`, `value`) : les données des graphiques |
| `GET /api/runs/{run_id}/analysis/insights` | les insights, et qui les a écrits : `llm` (chaque nombre vérifié) ou `fallback` |
| `GET /api/catalog` | le catalogue des KPI approuvé |
| `GET /api/glossary` | le glossaire (les mots de la manager vers les noms du catalogue) |
| `POST /api/kpis/preview` | calcule un KPI sur l'entrepôt d'un run, avec les contrôles. **Lecture seule** : rien n'est écrit |
| `POST /api/runs/{run_id}/kpi-proposal` | un **brouillon** de catalogue et de glossaire pour l'entrepôt d'un run. Rien n'est écrit dans `kpi/catalog.yaml` |

## Les erreurs

| Code | Quand |
|---|---|
| **404** | run inconnu, ou résultat pas encore calculé |
| **409** | le run n'a pas encore ce qu'il faut pour l'Analyst (requête de Malek, entrepôt d'Ahmed…) ; le message dit ce qui manque |
| **400** | KPI inconnu, ou dimension non autorisée par le catalogue (le message donne les dimensions permises) |
| **422** | `run_id` invalide : seuls les lettres, les chiffres, `_` et `-` sont acceptés, donc impossible de sortir de `runs/` |

## Sécurité

- Seul `POST /api/runs/{run_id}/analysis` écrit quelque chose : les sorties de l'Analyst et ses lignes de journal, exactement comme quand l'orchestrateur le lance.
- CORS n'autorise que `http://localhost:3000` par défaut. On peut changer ça avec la variable `BIFLOW_CORS_ORIGINS` (valeurs séparées par des virgules).
- La clé Groq reste dans `.env`, côté serveur : elle n'est jamais envoyée au navigateur.

## Pour Next.js

```cmd
python -m analysis.api.export_openapi
npx openapi-typescript analysis/api/openapi.json -o <app-next>/src/lib/analyst-types.ts
```

Les types TypeScript viennent ainsi **des mêmes contrats Pydantic** que le code Python.

## Tests

```cmd
python -m pytest tests/test_analysis_api.py -v
```

Les tests utilisent un dossier temporaire et un faux LLM : ils ne touchent ni à `runs/` ni à Groq.
