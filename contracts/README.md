# BIFlow : les contrats

> À lire par toute l'équipe avant d'écrire une ligne de code d'agent.
> Version des contrats : **1.0** (20 octobre 2026).

## 1. C'est quoi un contrat, en une phrase

Un contrat est **un accord sur la forme** de ce qu'un agent donne à un autre : le nom du fichier, les champs qu'il contient et leur type.

Une fois la forme fixée, personne n'attend personne. Tu fabriques un **faux fichier** de la bonne forme (il est déjà fourni dans `examples/`) et tu codes avec. Le jour où le vrai fichier arrive, ton code marche sans changement.

Chaque contrat est une **classe Pydantic**. Si un fichier n'a pas la bonne forme (champ manquant, faute de frappe, mauvais type), `load()` lève une erreur **tout de suite**, au lieu de laisser une donnée fausse traverser tout le pipeline.

## 2. Ce qu'il y a dans ce dossier

| Fichier | Ce qu'il contient | Propriétaire |
|---|---|---|
| `common.py` | Les briques communes : noms des étapes, types sémantiques des colonnes, `Period`, `save()` et `load()` | toute l'équipe |
| `agent.py` | **La prise** : `RunContext` (ce que l'agent reçoit), `AgentResult` (ce qu'il rend), `AgentStatus` | Samar |
| `pipeline.py` | **Le DAG** : qui lit quoi, sous quel nom de fichier chacun écrit, et `context_for()` | Samar |
| `audit.py` | **Le journal d'audit** partagé, en ajout seul et chaîné par hash | Tasnim |
| `intake.py` | Upload, similarité (0), types de colonnes (1a) | Malek, Samar |
| `privacy.py` | Rapport PII (1b) | Ikbel |
| `quality.py` | Profil, anomalies (2), règles, playbooks, rapport de nettoyage (2a/2b) | Ahmed, Ikbel |
| `warehouse.py` | Manifeste de l'entrepôt, reçus de transformation, graphe de lignage (3) | Ahmed |
| `semantic.py` | Catalogue KPI, glossaire, `AnalysisRequest` (4) | Rabeb, Malek |
| `analysis.py` | Résultat de l'Analyst (5) | Rabeb |
| `comparisons.py` | Contrôle des comparaisons trompeuses (6, BO4-12) | Tasnim |
| `dashboard.py` | Description du dashboard (6) | Samar |
| `xai.py` | Explications SHAP et rapport de drift (7) | Tasnim |
| `registry.py` | Quelle classe correspond à quel fichier, et `read_output()` | toute l'équipe |
| `check_contracts.py` | Le test à lancer avant toute modification | toute l'équipe |
| `examples/` | Un **run complet fictif** sur Olist + catalogue, glossaire et playbook d'exemple | toute l'équipe |

L'ancien `artifacts.py` est remplacé : son contenu est réparti dans les fichiers ci-dessus.

## 3. Le pipeline : qui écrit, qui lit

Tous les fichiers d'un run sont rangés dans `runs/<run_id>/<étape>/`. Les noms de fichiers sont **fixés** dans `pipeline.py`.

```
upload (app) ─┬─► similarity (0) ──────────────────────────┐
              ├─► column_types (1a) ─► pii (1b) ─► profiling (2) ─► cleaning (2a/2b) ─► etl (3)
              └─► request (4, BO4-06)                                                      │
                        │                                    ┌─────────────────────────────┤
                        └──────────────► analysis (5) ◄──────┘                    lineage ◄┘
                                            │
                                     comparisons (6, BO4-12)
                                            │
                                       dashboard (6) ─► auditor (7, en dernier)
```

Trois étapes peuvent tourner **en parallèle** dès le départ : `similarity`, `column_types` et `request`. Plus tard, `analysis` et `lineage` tournent aussi en même temps.

| Étape | Qui | Écrit (dans `runs/<run_id>/<étape>/`) | Lit |
|---|---|---|---|
| `upload` | Samar | `upload.json`, `tables/` (CSV bruts) | rien |
| `similarity` | Malek | `similarity_report.json` | upload |
| `column_types` | Malek | `column_types.json` | upload/tables |
| `pii` | Ikbel | `pii_report.json`, `tables/` (Parquet masqué) | upload/tables, column_types |
| `profiling` | Ahmed | `profile_report.json`, `anomaly_report.json`, `anomaly_model.joblib`, `anomaly_scores.parquet` | pii/tables, column_types |
| `cleaning` | Ikbel | `cleaning_report.json`, `tables/` (Parquet propre) | pii/tables, profil, similarité, playbooks |
| `etl` | Ahmed | `warehouse.duckdb`, `warehouse_manifest.json`, `receipts.json` | cleaning/tables |
| `request` | Malek | `analysis_request.json` | question, glossaire, catalogue |
| `analysis` | Rabeb | `analysis_result.json`, `result.parquet` | request, entrepôt, manifeste, reçus, catalogue |
| `comparisons` | Tasnim | `comparison_report.json` | request, résultat, entrepôt, manifeste, reçus, catalogue |
| `dashboard` | Samar | `dashboard_spec.json` | request, résultat, comparaisons |
| `lineage` | Ahmed | `lineage.json` | reçus, manifeste, catalogue |
| `auditor` | Tasnim | `explanations.json`, `drift_report.json`, `integrity_report.json` | anomalies, modèle, scores, lignage, **journal** |

Trois fichiers ne sont pas produits par un run. Ils sont **versionnés dans le dépôt** :

- `kpi/catalog.yaml` (Rabeb) : les KPI avec leur formule SQL, leur version et leur granularité.
- `semantic/glossary.yaml` (Rabeb) : les synonymes, par exemple « ventes » = Revenue et « région » = customer_state.
- `cleaning/playbooks/<nom>@<version>.yaml` (Ikbel) : les règles de nettoyage approuvées.

**Règle de confidentialité :** à partir de `pii`, plus aucun agent ne lit les fichiers bruts de l'upload.

## 4. Travailler seul, en 3 commandes

Toutes les commandes se lancent **depuis la racine du projet** (`biflow/`).

```bash
pip install "pydantic>=2" pyyaml
python -m contracts.examples.install    # copie le faux run dans runs/run_001/ et les YAML à leur place
python -m contracts.check_contracts     # vérifie que tout est cohérent
```

Ensuite, dans tes tests, tu demandes **exactement** le contexte que l'orchestrateur te donnera :

```python
from contracts import context_for
ctx = context_for("comparisons", "run_001")
print(ctx.inputs)   # chemins de tous tes fichiers d'entrée, déjà remplis par les exemples
```

Les exemples contiennent tous les **JSON**. Les fichiers de données (Parquet, `warehouse.duckdb`, modèle `.joblib`) ne sont pas dans les exemples. Si tu en as besoin avant que leur propriétaire ait fini, fabrique-en une petite version à partir de l'échantillon `data/sample/`.

## 5. Le modèle d'un agent

Chaque agent suit ce schéma. Ici, une version simplifiée de l'agent `comparisons` :

```python
from contracts import AgentResult, AgentStatus, RunContext, save
from contracts.comparisons import ComparisonReport
from contracts.registry import read_output


def run(ctx: RunContext) -> AgentResult:
    # 1. LIRE : read_output valide le fichier contre son contrat
    request = read_output(ctx.inputs["request"], "request.request")

    # 2. TRAVAILLER
    report = ComparisonReport(has_comparison=request.compare_to is not None)

    # 3. JOURNALISER chaque décision importante
    ctx.log("comparison_detected", str(report.has_comparison),
            inputs=[str(ctx.inputs["request"])],
            evidence={"compare_to": request.compare_to and request.compare_to.model_dump()})

    # 4. ÉCRIRE sous le nom fixé par pipeline.py, puis RENDRE le reçu
    path = save(report, ctx.output("report"))
    status = AgentStatus.SUCCESS if report.has_comparison else AgentStatus.SKIPPED
    return AgentResult(run_id=ctx.run_id, agent=ctx.agent, status=status,
                       outputs={"report": path}, message="Comparison checked.")
```

Le chemin `module:fonction` de chaque agent est dans `pipeline.py`, colonne `entrypoint`. Par exemple, l'orchestrateur appellera `comparisons.checker:run`.

Ce que chaque statut veut dire pour l'orchestrateur :

| Statut | Quand l'utiliser | Ce que fait l'orchestrateur |
|---|---|---|
| `success` | Tout s'est bien passé | Il lance les étapes suivantes |
| `failed` | Erreur bloquante | Il arrête les étapes qui dépendent de celle-ci |
| `needs_review` | Un humain doit confirmer (nouvelles règles LLM, correction d'une comparaison…) | Il met en pause et l'app pose la question |
| `skipped` | Rien à faire (par exemple, pas de comparaison demandée) | Il continue normalement |

## 6. Le journal d'audit (tout le monde l'utilise)

**Règle :** une ligne par **décision importante**, pas par ligne de données. Exemples de décisions importantes :

- une colonne masquée ;
- une règle de nettoyage appliquée ;
- une jointure vérifiée ;
- une version de KPI choisie ;
- un type de graphique choisi ;
- une comparaison bloquée.

Le plus simple est d'utiliser le raccourci du contexte :

```python
ctx.log(step="R4_fill_median_weight",
        decision="filled 2 missing product_weight_g with the median 700",
        rule_version="playbook:olist@1.3",
        evidence={"rows_affected": 2, "median": 700})
```

Chaque ligne contient les champs suivants :

| Champ | Contenu |
|---|---|
| `run_id` | Le numéro du run |
| `agent` | Qui |
| `step` | Quoi |
| `decision` | La décision prise |
| `timestamp` | Quand |
| `inputs` / `outputs` | Ce qui a été lu et écrit |
| `rule_version` | La version de la règle ou du KPI |
| `evidence` | Les chiffres qui justifient la décision |

Le format de `rule_version` est `type:nom@version`, par exemple `kpi:Revenue@2.0`, `playbook:olist@1.3` ou `pii-policy@1.0`. C'est ce champ qui permet à l'Auditor de répondre à « pourquoi ? ».

Pourquoi SQLite et pas un simple fichier texte ? Parce que les agents écrivent **en même temps**. La base garantit que deux écritures simultanées ne cassent jamais la chaîne. Le journal est aussi protégé de deux façons :

- les commandes `UPDATE` et `DELETE` sont refusées ;
- `verify_journal()` détecte toute ligne modifiée, supprimée ou insérée.

Des exemples de lignes pour chaque agent sont dans `examples/audit_events.json`.

## 7. Le scénario des exemples

Sarra dépose les tables Olist et demande : *« Revenue by state in August 2018 compared with July 2018 »*.

Les comptes de lignes et les chiffres d'affaires des exemples sont **réels** : ils ont été calculés sur le dataset Olist complet. Les scores, valeurs SHAP et taux de confiance sont fictifs.

Ce scénario montre pourquoi BO4-12 existe :

| Comparaison | Août | Juillet | Évolution |
|---|---|---|---|
| Mois entiers | 985 414 BRL | 1 027 904 BRL | **−4,1 %** (fausse baisse) |
| Du 1er au 29 | 985 414 BRL | 930 970 BRL | **+5,8 %** |

Les données livrées d'août s'arrêtent le 29. Le contrôle `coverage` bloque donc la première comparaison et propose la seconde.

## 8. Règles de l'équipe

1. **Ne jamais modifier un contrat seul.** Toute modification passe par une petite pull request que toute l'équipe voit. Les personnes qui lisent le fichier modifié doivent être d'accord.
2. **Avant chaque pull request** sur `contracts/`, lance `python -m contracts.check_contracts` et `python -m contracts.examples.build_examples` (ce dernier régénère les exemples).
3. **Ajouter un champ optionnel** (avec une valeur par défaut) ne casse personne. **Renommer ou supprimer** un champ casse quelqu'un : dans ce cas, il faut augmenter `CONTRACTS_VERSION` dans `common.py`.
4. **Un agent n'importe jamais le code d'un autre agent.** Il importe seulement `contracts`.
5. Les fichiers qui ne vont pas dans Git (à mettre dans `.gitignore`) : `runs/`, `*.db`, `*.duckdb`, `.venv/`, `__pycache__/`, et les CSV Olist complets (on ne versionne que `data/sample/`).

## 9. À valider ensemble à la première réunion

Ces choix ont été faits pour pouvoir démarrer. Chacun relit **la partie qui le concerne** et dit si ça lui convient.

- **Malek** :
  - la liste `SemanticType` (`common.py`) ;
  - le seuil de similarité ;
  - le champ `matched_terms` de la requête.
- **Ikbel** :
  - les actions possibles d'une règle (`CleaningAction`) ;
  - la politique PII (quelles colonnes Olist sont masquées, et comment).
- **Ahmed** :
  - la liste des tables de l'entrepôt et leur granularité ;
  - la table sur laquelle tourne la détection d'anomalies (`order_payments` dans l'exemple).
- **Rabeb** :
  - les KPI du catalogue (Revenue@2.0, Orders@1.0) et leurs filtres ;
  - le format de `result.parquet` (dimensions + `period` + `value`).
- **Samar** :
  - les types de graphiques (`ChartType`) ;
  - le comportement de l'orchestrateur pour `needs_review` et `skipped`.
- **Tasnim** :
  - les 4 contrôles de comparaison (`coverage`, `unit`, `grain`, `population`) ;
  - le format du rapport de drift (les runs de référence = des runs mensuels sur Olist).
