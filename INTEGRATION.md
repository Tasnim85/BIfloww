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

Tests : **474 réussis**. Les 2 échecs restants viennent seulement de l'environnement : `sentence-transformers` n'est pas
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

| `orchestrator/dag_runner.py` (Samar) | une étape en `needs_review` ne bloquait pas la suite : les étapes suivantes tournaient sans leurs fichiers et plantaient | elles attendent (« Waiting for the human review of … ») ; on relance le **même** `run_id` après la revue, les étapes finies sont réutilisées |
| `privacy/agent.py`, `privacy/models.py` (Ikbel) | si llama3 hésite sur une colonne, le PII s'arrête et **rien ne permettait à un humain de trancher** (seul choix : tout masquer, donc perdre `customer_state`) | paramètre `pii_overrides` : le relecteur donne le type des colonnes douteuses, inscrit au journal (`human_review`) |
| `comparisons/checker.py`, `comparisons/data.py` (Tasnim) | au redémarrage après la décision de Sarra, la comparaison était recalculée et la décision oubliée ; si l'entrepôt n'a pas une colonne du KPI, erreur SQL incompréhensible | la décision est gardée ; message clair qui pointe vers `check_warehouse` |

Tests de non-régression : `tests/test_integration_fixes.py`, `tests/test_comparisons.py`.

## Ce que le vrai llama3 pourrait faire autrement (testé avec un faux Ollama « qui se trompe »)

Ollama ne peut pas être installé dans l'environnement de test. `tools/integration/fake_ollama.py` imite donc les réponses
plausibles de llama3 (`FAKE_SCENARIO=...`), y compris ses erreurs :

| Scénario | Résultat |
|---|---|
| `ideal` : réponses attendues | ✅ tout passe, mêmes chiffres |
| `orders_fact` : `orders` classé comme fait | ✅ tout passe, mêmes chiffres (985 414,28 vs 1 027 903,86 BRL) |
| `star` : schéma en étoile au lieu de constellation | ✅ tout passe, mêmes chiffres |
| `drop_links` : refuse la moitié des relations | ✅ analyse et comparaisons OK ; le lignage refuse (« KPI grain/date ») |
| `drop_payment_link` : refuse `order_payments → orders` | ❌ l'entrepôt perd `order_status` et la date : **`check_warehouse` le détecte** et dit quelle relation rajouter ; après correction du plan → ✅ |
| `pii_unsure` : hésite sur `customer_state` | ⏸ le PII attend → `pii_overrides` → ✅ tout passe |

**Boucle complète testée** (`tools/integration/run_with_reviews.py`) avec l'orchestrateur de Samar : PII en revue →
ETL en revue → décision de Sarra → tout ✅, en reprenant le même `run_id` à chaque tour.

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

- **Avant de lancer** : Ollama avec `llama3` (PII et ETL), `BO2_PII_SECRET` (32 caractères au moins) et
  `OLLAMA_TIMEOUT=600` (sur un PC sans carte graphique, une réponse peut dépasser les 240 s par défaut).
- **Paramètres à passer** : `playbook=cleaning/playbooks/playbook_v2.0.json` (point 2) et `backend=json` (point 4).
- **Les pauses humaines** (`needs_review`) : les étapes suivantes attendent. Après la réponse, relancer `run_pipeline`
  avec le **même** `run_id` et le paramètre ajouté :

  | Étape en pause | Ce que l'humain fait | Paramètre / appel pour reprendre |
  |---|---|---|
  | `pii` (si llama3 hésite) | donne le type des colonnes listées dans `pii/pii_report.bo2.json` → `needs_review` | `pii_overrides={"customers.customer_state": "CATEGORY"}` |
  | `etl` (toujours) | relit `etl/warehouse_proposal.json` | `etl_approval=<sha256 du fichier>` |
  | `comparisons` (si bloquée) | Sarra choisit | `comparisons.checker.record_decision(run_id, "accepted")` (ou l'API) |

- **Juste après l'ETL**, lancer `python -m tools.integration.check_warehouse <run_id>` : il dit si chaque KPI du
  catalogue est calculable, et sinon quelle relation le plan a oubliée.
- **Exemple complet de la boucle** : `tools/integration/run_with_reviews.py` (à copier dans l'orchestrateur ou l'app).
- **Scripts** :
  ```
  python -m tools.integration.run_with_reviews integ_001      (tout, avec les revues)
  python -m tools.integration.check_warehouse integ_001
  python -m tools.integration.run_all integ_001               (un seul passage, s'arrête à la 1re revue)
  python -m tools.integration.run_from integ_001 etl etl_approval=<sha256> backend=json
  ```

## Tester sans Ollama

`tools/integration/fake_ollama.py` est une **doublure de test** : un faux Ollama local qui répond aux questions du PII
et de l'ETL avec des règles simples (`set FAKE_SCENARIO=ideal`, `orders_fact`, `star`, `drop_links`, `drop_payment_link`
ou `pii_unsure`). Il sert à vérifier que les données circulent entre les agents, **jamais à la
démo** : la qualité des décisions vient du vrai llama3.
