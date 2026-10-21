# Intégration de la partie IA (feature/rabeb + feature/tasnim)

`feature/rabeb` (Rabeb, avec les travaux de Malek, Ahmed et Ikbel) fusionnée dans `feature/tasnim` (BO3 Auditor + BO4-12).
`api/` et `web/` ne sont pas touchés.

## Résultat

Les 13 étapes tournent avec les **vrais agents** sur les 8 CSV Olist complets, avec la question
« Revenue by customer state, August 2018 vs July 2018 » :

| Étape | Résultat |
|---|---|
| upload, similarity, column_types, request | ✅ |
| pii → profiling → cleaning | ✅ |
| etl | ⏸ attend la validation humaine du schéma (voulu), puis ✅ constellation |
| analysis | ✅ Revenue@2.0, 4 contrôles OK |
| lineage | ✅ (backend `json`) |
| comparisons (BO4-12) | ⏸ comparaison bloquée et correction proposée (voulu) : −4,1 % demandé, **+34,6 %** sur les mêmes jours |
| dashboard | ✅ |
| auditor (BO3) | ✅ 1 031 anomalies expliquées sur le **vrai modèle d'Ahmed**, journal intact |

Tests : **470 réussis**. Les 2 échecs restants viennent seulement de l'environnement : `sentence-transformers` n'est pas
installé (`pip install -r requirements.txt` les règle).

## Conflits de fusion (3)

- `kpi/catalog.yaml` et `semantic/glossary.yaml` : version de Rabeb gardée (elle contient l'ancienne : mêmes définitions de Revenue et Orders, plus 4 KPI).
- `.gitignore` : union des deux.
- `contracts/` : aucun conflit, tout le monde est en **v1.6**.

## Corrections faites pendant l'intégration

| Fichier | Problème | Correction |
|---|---|---|
| `auditor/xai/shap_explainer.py`, `explain.py`, `auditor/drift/observe.py` (Tasnim) | le profiler d'Ahmed livre un `Pipeline` (imputer → IsolationForest) et une clé de ligne entière : SHAP plantait | l'Auditor sépare le pré-traitement et la forêt, et garde la clé d'origine |
| `etl/analytics.py` (Ahmed) | le PII publie `order_payments` au lieu de `olist_order_payments_dataset` : les vues prenaient des noms génériques (`fact_order_payments`) et le catalogue (`fact_payments`) ne les trouvait plus → analyse, comparaisons et lignage échouaient | les noms de vues acceptent les deux écritures |

Tests de non-régression : `tests/test_integration_fixes.py`.

## À corriger par leurs auteurs (rien ne bloque)

1. **Ikbel, PII** : les indices de Malek (`column_types`) ne sont jamais utilisés, car le PII renomme les tables
   (`olist_customers_dataset` → `customers`) avant de les chercher. À aligner les deux noms.
2. **Ikbel, Cleaning** : plusieurs familles de playbooks sont compatibles (`olist@1.3`, `cleaning` 1.0 et 2.0) et le cleaning
   s'arrête (« Several playbook families need explicit selection ») au lieu de prendre celui proposé par la similarité.
   Aujourd'hui il faut passer `playbook=cleaning/playbooks/playbook_v2.0.json`. `olist@1.3` est refusé
   (« modify a protected column »).
3. **Malek / Samar, upload ou column_types** : la colonne `product_category_name` du fichier de traduction garde le BOM
   (`﻿product_category_name`). Lire les CSV en `utf-8-sig`.
4. **Ahmed, Lineage** : le backend par défaut est Neo4j (il faut un serveur Neo4j et `NEO4J_PASSWORD`). Sans Neo4j :
   paramètre `backend=json`.

## Pour Samar (orchestrateur)

- **Avant de lancer** : Ollama avec `llama3` (utilisé par PII et ETL) et `BO2_PII_SECRET` (32 caractères au moins).
- **Paramètres à passer** : `playbook=…` (voir point 2) et `backend=json` si Neo4j n'est pas installé.
- **Deux pauses humaines** (`needs_review`) :
  1. **ETL** : l'utilisateur valide `runs/<run>/etl/warehouse_proposal.json`, puis on relance l'ETL avec
     `etl_approval=<sha256 du fichier>` ;
  2. **Comparaisons** : l'utilisateur choisit la correction (`comparisons.checker --accept same_days` ou l'API), puis on
     relance le dashboard et l'auditor.
- **Scripts prêts** :
  ```
  python -m tools.integration.run_all integ_001
  python -m tools.integration.run_from integ_001 etl etl_approval=<sha256> backend=json
  ```

## Tester sans Ollama

`tools/integration/fake_ollama.py` est une **doublure de test** : un faux Ollama local qui répond aux questions du PII
et de l'ETL avec des règles simples. Il sert à vérifier que les données circulent entre les agents, **jamais à la
démo** : la qualité des décisions vient du vrai llama3.
