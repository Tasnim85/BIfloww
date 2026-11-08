# API BIFlow — partie de Tasnim (étape 6)

L'API expose les agents BO4-12 (comparaisons) et BO3 (Auditor) en HTTP, pour l'application Next.js.
Elle ne contient **aucune logique métier** : elle lit les fichiers de contrat de `runs/<run_id>/`,
appelle les mêmes fonctions que Streamlit et renvoie les contrats tels quels.

## Lancer

```cmd
pip install fastapi "uvicorn[standard]" httpx
uvicorn api.main:app --reload --port 8000
```

Documentation interactive : http://localhost:8000/docs (on peut tester chaque route avec « Try it out »).

Toutes les routes commencent par **`/api`** (par exemple `GET /api/runs/run_001`), sauf `/health`.

## Deux fichiers

| Fichier | Rôle |
|---|---|
| `api/router.py` | **toutes les routes**, sous forme d'`APIRouter` : c'est ce que l'équipe intègre |
| `api/main.py` | l'app **autonome** de Tasnim (router + `/health` + CORS), pour ses tests et la démo |

## Intégration dans l'API commune de l'équipe (une ligne)

```python
from fastapi import FastAPI
from api.router import router as tasnim_router

app = FastAPI(title="BIFlow")
app.include_router(tasnim_router, prefix="/api")      # même préfixe : Next.js ne change pas
# app.include_router(orchestrator_router, prefix="/api")   # les routes des autres
```

Routes déjà prises par Tasnim (à ne pas réutiliser) : `GET /api/runs`, `GET /api/runs/{run_id}` et
tout ce qui est en dessous (`/comparison`, `/dashboard`, `/explanations`, `/why`, `/journal`, `/drift`),
`POST /api/comparisons`, `/api/journals/...`, `GET /api/drift`. L'orchestrateur peut ajouter
`POST /api/runs` (déposer un CSV + une question) et `GET /api/runs/{run_id}/status` sans conflit.

## En production : cacher les journaux de démo

```cmd
set BIFLOW_JOURNALS=real,ui
```
Sans cette variable, tous les journaux sont visibles (demo, drift, clinics, ui, real). Elle s'applique
aussi à Streamlit.

## Les routes

| Route | Rôle |
|---|---|
| `GET /health` (app autonome) | version des contrats, LLM prêt ou non, journaux présents |
| `GET /api/runs` | les runs et ce que chacun contient |
| `GET /api/runs/{run_id}` | **tout l'écran de résultat en un appel** : question, verdict BO4-12, périodes du dashboard, intégrité, anomalies, drift |
| `GET /api/runs/{run_id}/comparison` | le rapport BO4-12 |
| `POST /api/runs/{run_id}/comparison/decision` | la décision de l'utilisateur (`accepted` + `chosen_fix`, `rejected`, `pending`), inscrite au journal |
| `POST /api/comparisons` | une nouvelle question : lance **l'Analyste de Rabeb** puis le vrai agent BO4-12 (crée un run `custom_xxxx`, journal « ui ») |
| `GET /api/runs/{run_id}/pipeline` | **ce que chaque agent a écrit** (similarité, types, PII, profilage, nettoyage, entrepôt, lignage, demande, analyse), lu dans les fichiers de contrat uniquement (`api/stages.py`). Un run `custom_*` montre les étapes de données de son run de base (`source_run`) |
| `POST /api/uploads` | **la réception de Samar** : les fichiers CSV de l'utilisateur + sa question passent par **tout le DAG** (orchestrateur de Samar), en arrière-plan. Crée un run `up_xxxxxxxxxxxx` (`api/jobs.py`) |
| `GET /api/runs/{run_id}/progress` | l'état des 13 étapes d'un run `up_*`, et la validation humaine attendue (PII ou ETL) |
| `POST /api/runs/{run_id}/review` | la réponse de l'utilisateur (valider / refuser) à la revue PII ou ETL, inscrite au journal ; le run reprend. La revue de comparaison passe par `comparison/decision` |
| `GET /api/runs/{run_id}/charts` | **le tableau de bord de Samar** (`dashboard_ai`) : graphiques choisis, leurs données, la raison du choix, les options refusées, les alertes |
| `POST /api/parse` | **l'agent de Malek** lit une question en langage courant et propose KPI, dimensions, périodes. Simple proposition : journal temporaire, rien n'est calculé |
| `GET /api/runs/{run_id}/dashboard` | le KPI par dimension pour les périodes fixées par la décision ; **409** tant qu'une comparaison bloquée attend la décision |
| `GET /api/runs/{run_id}/explanations` | explications SHAP (pagination `offset` / `limit`) |
| `GET /api/runs/{run_id}/explanations/{row_key}` | l'explication d'une ligne |
| `POST /api/runs/{run_id}/why` | l'agent « pourquoi ? » (LLM + outils, chaque chiffre vérifié) |
| `GET /api/runs/{run_id}/journal` | les décisions du run |
| `GET /api/journals`, `/api/journals/{id}/entries`, `/api/journals/{id}/verify` | les journaux et la vérification de la chaîne de hachage |
| `GET /api/runs/{run_id}/drift`, `GET /api/drift` | les rapports de drift |

## Envoyer ses propres fichiers (réception + tableau de bord de Samar)

Il faut, côté Python (dans `.env` à la racine, jamais sur GitHub) : `BO2_PII_SECRET=<32 caractères ou plus>`, et Ollama
avec `llama3` (ou, pour les tests seulement, `python tools\integration\fake_ollama.py`). `pip install python-multipart`.
`GET /health` dit si le LLM local est joignable (`local_llm`) et si c'est la doublure (`test_double`) : dans ce cas les
décisions vont dans `runs/integration_journal.db`, jamais dans le journal réel. Limites : 20 fichiers, 150 Mo par fichier,
300 Mo en tout, 2 pipelines en même temps. Un jeu envoyé par un utilisateur n'est jamais proposé aux autres.

Validations humaines dans l'app (PII, règles de nettoyage, schéma ETL, comparaison) : le **nom de l'utilisateur connecté**
(mis par le serveur Next.js, jamais tapé dans le navigateur) et l'**heure** vont dans le journal (`human_review` /
`user_decision`) et dans `runs/<run>/<étape>/approval.json`. Pour montrer la validation des règles de nettoyage
proposées par le LLM (quand aucun playbook validé ne convient) : lancer l'API avec `set BIFLOW_CLEANING_MODE=generate`.

## Langue des textes (français / anglais)

Toutes les routes qui renvoient du texte acceptent **`?lang=fr`** ou **`?lang=en`**. Sans ce paramètre, la langue vient de l'en-tête `Accept-Language` du navigateur, sinon c'est le français. Les nombres ne changent pas : seule leur écriture change (941 291,36 contre 941,291.36). Pour `POST /api/runs/{run_id}/why`, la réponse est dans la langue de la question (détectée), sauf si `lang` est donné dans le corps. Détails : `i18n/README.md`.

## Sécurité

- Un `run_id` ne peut contenir que lettres, chiffres, `_` et `-` : impossible de sortir de `runs/`.
- Seuls les journaux connus et visibles sont accessibles (`BIFLOW_JOURNALS`).
- Les comparaisons créées par l'API vont dans le journal `ui`, jamais dans le journal réel.
- CORS : seulement `http://localhost:3000` par défaut (variable `BIFLOW_CORS_ORIGINS`, séparée par des virgules).

## Pour Next.js (étape 7)

```cmd
python -m api.export_openapi
npx openapi-typescript api/openapi.json -o <app-next>/src/lib/api-types.ts
```

Les types TypeScript viennent ainsi des **mêmes contrats Pydantic**.
