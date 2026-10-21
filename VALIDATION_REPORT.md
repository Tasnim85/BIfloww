# BIFlow — Étape 1 & BO1/BO4 Foundation — Validation Report

**Branche :** `fix/biflow-audit-findings` (synchronisée avec `BO1/Samar+Malek`)  
**Commit de départ :** `5dcb84b`  
**Date :** 2026-10-21  
**Python :** 3.13.0  
**OS :** Windows 11 (PowerShell)

---

## 1. Résultats des tests (mesurés réellement le 2026-10-21)

### Total Exécuté

```text
179 passed, 2 warnings in 33.93s
```

Les 2 warnings sont des DeprecationWarning de `traitlets` et `zmq` sous Windows (non bloquants). Aucun échec, aucune régression.

### Répartition exacte par suite de tests (15 fichiers, 179 tests)

| Fichier de tests | Tests | Statut | Couverture / Responsable |
|---|:---:|:---:|---|
| `intake/semantic_detection/tests/test_taxonomy.py` | 26 | 26 passed | Validation stricte YAML & Loader (Malek) |
| `intake/semantic_detection/tests/test_contracts.py` | 25 | 25 passed | Contrats Pydantic v2 & validation (Malek) |
| `intake/semantic_detection/tests/test_examples.py` | 4 | 4 passed | Intégrité des exemples JSON (Malek) |
| `tests/test_olist_columns.py` | 39 | 39 passed | Classification des colonnes Olist (Malek) |
| `tests/test_dag_runner.py` | 8 | 8 passed | DAG runner, concurrence, reprise, cycles (Samar) |
| `tests/test_dashboard.py` | 9 | 9 passed | Sélection de graphiques, DashboardSpec & barres groupées multi-dim (Samar) |
| `tests/test_chart_rendering.py` | 5 | 5 passed | Rendu des graphiques Streamlit dont barres groupées (Samar) |
| `tests/test_request.py` | 13 | 13 passed | Analyse de requêtes, embeddings, détection périodes & NEEDS_REVIEW (Malek) |
| `tests/test_request_synonyms.py` | 18 | 18 passed | Synonymes métier, mois français, regex frontières (BO4-06) |
| `tests/test_notebook.py` | 5 | 5 passed | Exécutabilité des 12 sections du notebook |
| `tests/test_sample_integrity.py` | 11 | 11 passed | 8 tables, 500 commandes, PK/FK & traduction catégories |
| `tests/test_similarity_embeddings.py` | 4 | 4 passed | BO1-06 Similarité vectorielle Embeddings vs Jaccard |
| `tests/test_ner_extraction.py` | 1 | 1 passed | Inspection NER sur 5 questions diverses (Malek) |
| `tests/test_execution_order.py` | 9 | 9 passed | Ordre d'exécution topologique DAG (Samar) |
| `tests/test_pipeline_e2e.py` | 2 | 2 passed | E2E pipeline : échec réel explicite vs succès simulé |
| **Total Global** | **179** | **179 passed** | **100% succès (0 échec)** |

---

## 2. python -m contracts.check_contracts (réel)

```text
OK  DAG: upload -> similarity -> column_types -> request -> pii -> profiling -> cleaning -> etl -> analysis -> lineage -> comparisons -> dashboard -> auditor
OK  18 example JSON files + 3 YAML files are valid
OK  BO4-12 example: last complete day 2018-08-23 follows from the coverage profile
OK  journal: 40 parallel writes, chain intact
OK  journal: tampering with entry 5 detected -> Entry 5: content does not match its hash. It was modified after being written.
All contract checks passed.
```

---

## 3. Graphiques Multi-Dimensionnels & Barres Groupées (Samar / Dashboard)

- **Contrat partagé préservé :** `contracts/dashboard.py` conserve son énumération gelée (`kpi_card`, `bar`, `line`, `map`, `pie`, `table`). Aucun type hors contrat (`grouped_bar`, `heatmap`) n'a été injecté.
- **Liaison des dimensions :** dans `app/dashboard.py`, lorsqu'une requête comporte 2 dimensions sans comparaison temporelle, l'axe X reçoit `request.dimensions[0]` et l'axe de regroupement (`color`) reçoit explicitement la deuxième dimension `request.dimensions[1]`.
- **Validation fonctionnelle :**
  - `tests/test_dashboard.py::test_two_dims_sets_color_for_grouped_bar` valide que `spec.charts[0].color == "payment_type"` et que le motif `grouped bar` est documenté dans le champ `reason`.
  - `tests/test_chart_rendering.py::test_chart_spec_grouped_bar_chart` valide la structure Parquet et le pivot multi-dimensions conforme aux attentes de rendu Streamlit (`st.bar_chart(df, x=x, y=y, color=color)`).

---

## 4. BO4-06 : Recherche Sémantique par Embeddings & Gestion d'Absence de Période (Malek)

- **Recherche par Embeddings intégrée :** `semantic/request.py` exploite Sentence-Transformers (`all-MiniLM-L6-v2`) pour calculer la similarité cosinus entre la question normalisée et les descriptions textuelles du glossaire et du catalogue KPI (`_find_metric`, Tier 4).
- **Gestion des questions sans période :** selon la spécification, une question valide sans repère temporel déclenche `AgentStatus.NEEDS_REVIEW` avec la raison `"no time period found"`. Couvert par tests unitaires (`tests/test_request.py`) et benchmark (`Q11_NO_PERIOD`).
- **Benchmark étendu via l'entrypoint réel `run(ctx)` (11 cas) :**
  ```text
  BENCHMARK COMPONENT ACCURACY SUMMARY (N=11)
    * Entrypoint run(ctx) Success : 11/11 (100.0%)
    * Metrics Extraction          : 11/11 (100.0%)
    * Exact Dimensions Match      : 11/11 (100.0%)
    * Periods & Comparisons       : 11/11 (100.0%)
    * Filters & Constraints       : 11/11 (100.0%)
    GLOBAL FULL ACCURACY          : 11/11 (100.0%)
  ```

---

## 5. BO1-06 : Recherche Vectorielle Embeddings vs Jaccard

| Scénario de Test | Jaccard | Embedding Cosine | Interprétation |
|---|:---:|:---:|---|
| **Olist Identique** | 1.0000 | 1.0000 | Match parfait |
| **Olist Renommé (Synonymes/FR)** | 0.0000 | 0.4324 | **Embeddings > Jaccard** (reconnaissance sémantique) |
| **Dataset Sans Rapport (Iris/Météo)** | 0.0000 | 0.1640 | Rejet net (non similaire) |

---

## 6. Thread-Safety & Streamlit (Samar)

- `app/app.py` découplé de toute mutation directe de `st.session_state` au sein de threads worker d'arrière-plan.
- Suivi d'état et progression interrogés depuis le thread principal Streamlit via la base SQLite `runs/task_store.db` (`get_run_status`).
- Absence totale d'accès concurrent dangereux sur le session state.

---

## 7. Intégrité des Données (Échantillon Olist & Traduction Catégories)

- 8 tables Olist complètes dans `data/sample/` (500 commandes exactes).
- Clés primaires strictement uniques.
- Clés étrangères 100% résolues sans orphelins (`test_sample_integrity.py`).
- Table de traduction des catégories de produits (`product_category_name_translation.csv`) créée et couvrant 100% des catégories.
- Documenté expressément comme **jeu de données synthétique de référence conforme** dans `data/sample/README.md`.

---

## 8. Statut de Déploiement E2E (Transparent & Vérifiable)

- **Mode simulé (Stubbed / Contrats) :** `SUCCESS` — le pipeline complet génère bien `dashboard_spec.json` lorsque tous les contrats amont et aval sont fournis.
- **Mode production réelle :** **BLOQUÉ** — tant que les agents métier indispensables des autres étapes (1b, 2, 2a, 3, 5, 6, 7) ne sont pas implémentés par leurs responsables respectifs, le dashboard réel ne peut pas être produit à partir de rien. Ce blocage est documenté de manière transparente.

---

## 9. Intégrité des Contrats Partagés

```text
git diff --stat contracts/ (hors proposals/) = 0 fichier modifié
```
Aucun contrat d'équipe partagé n'a été altéré.
