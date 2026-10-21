# BIFlow — Étape 1 & BO1/BO4 Foundation — Validation Report

**Branche :** `fix/biflow-audit-findings` (fondée sur `BO1/Samar+Malek`)  
**Commit de départ :** `5dcb84b`  
**Date :** 2026-10-21  
**Python :** 3.13.0  
**OS :** Windows 11 (PowerShell)

---

## 1. Résultats des tests (réels, obtenus le 2026-10-21)

### Total

```text
173 passed, 2 warnings in 36.17s
```

Les 2 warnings sont des DeprecationWarning de `traitlets` et `zmq` sur Windows (non bloquants).

### Répartition par suite de tests

| Fichier de tests | Tests | Statut | Couverture / Responsable |
|---|:---:|:---:|---|
| `intake/semantic_detection/tests/test_taxonomy.py` | 26 | 26 passed | Validation stricte YAML & Loader (Malek) |
| `intake/semantic_detection/tests/test_contracts.py` | 25 | 25 passed | Contrats Pydantic v2 & validation (Malek) |
| `intake/semantic_detection/tests/test_examples.py` | 4 | 4 passed | Intégrité des exemples JSON (Malek) |
| `tests/test_olist_columns.py` | 39 | 39 passed | Classification des colonnes Olist (Malek) |
| `tests/test_dag_runner.py` | 8 | 8 passed | DAG runner, concurrence, reprise, cycles (Samar) |
| `tests/test_dashboard.py` | 7 | 7 passed | Sélection de graphiques & DashboardSpec (Samar) |
| `tests/test_request.py` | 10 | 10 passed | Analyse de requêtes basiques (Malek) |
| `tests/test_request_synonyms.py` | 18 | 18 passed | Synonymes métier, mois français, regex frontières (BO4-06) |
| `tests/test_notebook.py` | 5 | 5 passed | Exécutabilité des 12 sections du notebook |
| `tests/test_sample_integrity.py` | 11 | 11 passed | 8 tables, 500 commandes, PK/FK & traduction catégories |
| `tests/test_similarity_embeddings.py` | 4 | 4 passed | BO1-06 Similarité vectorielle Embeddings vs Jaccard |
| `tests/test_chart_rendering.py` | 4 | 4 passed | Rendu des graphiques Streamlit (kpi, bar, line, table) |
| `tests/test_ner_extraction.py` | 1 | 1 passed | Inspection NER sur 5 questions diverses (Malek) |
| `tests/test_execution_order.py` | 9 | 9 passed | Ordre d'exécution topologique DAG (Samar) |
| `tests/test_pipeline_e2e.py` | 2 | 2 passed | E2E pipeline : échec réel explicite vs succès simulé |
| **Total Global** | **173** | **173 passed** | **100% succès (0 échec)** |

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

## 3. BO1-06 : Recherche Vectorielle Embeddings vs Jaccard

| Scénario de Test | Jaccard | Embedding Cosine | Interprétation |
|---|:---:|:---:|---|
| **Olist Identique** | 1.0000 | 1.0000 | Match parfait |
| **Olist Renommé (Synonymes/FR)** | 0.0000 | 0.4324 | **Embeddings > Jaccard** (reconnaissance sémantique) |
| **Dataset Sans Rapport (Iris/Météo)** | 0.0000 | 0.1640 | Rejet net (non similaire) |

---

## 4. BO4-06 : Benchmark Étendu (10/10 - 100% Précision)

Spécifications JSON attendues définies avant l'exécution dans `tests/benchmark_request.py` :
- **Extraction des métriques :** 10/10 (100.0%)
- **Dimensions exactes :** 10/10 (100.0%)
- **Périodes temporelles & Comparaisons :** 10/10 (100.0%)
- **Filtres & Contraintes (Top 5, Exclusion) :** 10/10 (100.0%)
- **Précision globale :** **10/10 (100.0%)**

---

## 5. Intégrité des Données (Échantillon Olist & Traduction Catégories)

- 8 tables Olist complètes dans `data/sample/` (500 commandes exactes).
- Clés primaires strictement uniques.
- Clés étrangères 100% résolues sans orphelins (`test_sample_integrity.py`).
- Table de traduction des catégories de produits (`product_category_name_translation.csv`) créée et couvrant 100% des catégories.
- Documenté expressément comme **jeu de données synthétique de référence conforme** dans `data/sample/README.md`.

---

## 6. Intégrité des Contrats Partagés

```text
git diff --stat contracts/ (hors proposals/) = 0 fichier modifié
```
Aucun contrat d'équipe partagé n'a été altéré.
