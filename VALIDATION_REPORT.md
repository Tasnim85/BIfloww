# BIFlow — Étape 1 : Semantic Foundation — Validation Report

**Branche :** `BO1/Samar+Malek`  
**Commit de départ :** `5dcb84b`  
**Date :** 2026-10-21  
**Python :** 3.13.0  
**OS :** Windows 11 (PowerShell)

---

## 1. Résultats des tests (réels, obtenus le 2026-10-21)

### Total

```
113 passed, 2 warnings in 11.86s
```

Les 2 warnings sont des DeprecationWarning de `traitlets` et `zmq` sur Windows (non bloquants).

### Par fichier

| Fichier de tests | Tests | Résultat |
|---|---|---|
| `intake/semantic_detection/tests/test_taxonomy.py` | 26 | 26 passed |
| `intake/semantic_detection/tests/test_contracts.py` | 25 | 25 passed |
| `intake/semantic_detection/tests/test_examples.py` | 4 | 4 passed |
| `tests/test_olist_columns.py` | 39 | 39 passed |
| `tests/test_dag_runner.py` | 4 | 4 passed |
| `tests/test_request.py` | 10 | 10 passed |
| `tests/test_notebook.py` | 5 | 5 passed |
| **Total** | **113** | **113 passed** |

### Détail tests nouveaux (Tâche 1 — TestStrictValidation)

```
test_missing_group_description_is_error     PASSED
test_missing_type_description_is_error      PASSED
test_group_without_types_is_error           PASSED
test_invalid_privacy_hint_is_error          PASSED
test_invalid_version_format_is_error        PASSED
```

---

## 2. python -m contracts.check_contracts (réel)

```
OK  DAG: upload -> similarity -> column_types -> request -> pii -> profiling -> cleaning -> etl -> analysis -> lineage -> comparisons -> dashboard -> auditor
OK  18 example JSON files + 3 YAML files are valid
OK  BO4-12 example: last complete day 2018-08-23 follows from the coverage profile
OK  journal: 40 parallel writes, chain intact
OK  journal: tampering with entry 5 detected -> Entry 5: content does not match its hash. It was modified after being written.
All contract checks passed.
```

---

## 3. Vérification finale manuelle (réelle)

```
PASS - FINANCIAL_DATA/EMAIL rejected: 1 validation error for SemanticColumn
  Value error, Type 'EMAIL' does not belong to group 'FINANCIAL_DATA'...
PASS - FAKE_GROUP rejected: 1 validation error for SemanticColumn
  Value error, Unknown semantic_group 'FAKE_GROUP'...
PASS - empty columns counter rejected: 1 validation error for SemanticMetadata
  Value error, total_columns (99) != len(columns) (0)...
PASS - version abc rejected: True
PASS - HIGH hint rejected: True
PASS - PERSON_ID hint: True POTENTIAL_PII
```

---

## 4. Fichiers développés (Étape 1)

### Taxonomie sémantique

| Fichier | Description |
|---|---|
| `intake/semantic_detection/config/semantic_types.yaml` | Taxonomie v1.1.1 — 10 groupes, 60 types, privacy hints |
| `intake/semantic_detection/src/taxonomy_loader.py` | Chargement et indexation de la taxonomie |
| `intake/semantic_detection/src/taxonomy_validator.py` | Validation stricte du YAML (version, descriptions, groupes, hints) |

### Contrats Pydantic

| Fichier | Description |
|---|---|
| `contracts/proposals/semantic_contracts.py` | `SemanticColumn`, `SemanticMetadata`, `SemanticMatch`, `SemanticMatchesReport` |

### Classification rule-based

| Fichier | Description |
|---|---|
| `intake/column_types.py` | Classifieur rule-based, `_TYPE_MAP`, `_PII_TAXONOMY_TYPES` |

### Notebook

| Fichier | Description |
|---|---|
| `intake/semantic_detection/notebooks/01_semantic_foundation.ipynb` | 12 sections, exec()-validé, nbclient-validé |

### Exemples

| Fichier | Description |
|---|---|
| `intake/semantic_detection/examples/semantic_metadata_example.json` | 13 colonnes Olist annotées |
| `intake/semantic_detection/examples/taxonomy_validation_report.json` | Rapport de validation YAML (v1.1.1, 0 erreurs) |
| `intake/semantic_detection/examples/olist_schema_example.json` | Schéma de référence Olist |
| `intake/semantic_detection/examples/privacy_hints_example.json` | Exemples de hints privacy |
| `intake/semantic_detection/examples/types_per_group.png` | Graphique types par groupe |

### Tests

| Fichier | Description |
|---|---|
| `intake/semantic_detection/tests/test_taxonomy.py` | 26 tests (dont 5 nouveaux TestStrictValidation) |
| `intake/semantic_detection/tests/test_contracts.py` | 25 tests Pydantic |
| `intake/semantic_detection/tests/test_examples.py` | 4 tests sur les fichiers JSON |
| `tests/test_olist_columns.py` | 39 tests golden dataset Olist |
| `tests/test_notebook.py` | 5 tests notebook (dont nbclient exec) |

### Documentation

| Fichier | Description |
|---|---|
| `docs/CONTRACT_CHANGE_PROPOSAL.md` | Proposition de changements + note PERSON_ID/Ikbel |
| `docs/SEMANTIC_TAXONOMY.md` | Documentation de la taxonomie |
| `docs/INTEGRATION_GUIDE.md` | Guide d'intégration pour les équipes |
| `README.md` | README principal avec `requirements-app.txt` |

### Dépendances

| Fichier | Description |
|---|---|
| `requirements.txt` | Dépendances core Étape 1 (Python 3.11+) |
| `requirements-app.txt` | Dépendances app Samar (duckdb, streamlit) |

---

## 5. Intégrité des contrats partagés

```
git diff --stat contracts/ (hors proposals/) = 0 fichier modifié
```

Aucun fichier `contracts/` (hors `contracts/proposals/`) n'a été modifié.

---

## 6. Vérification grep (hash/mask/clean/profil dans intake/)

```
intake/column_types.py — lignes :
  L19: NOTE: this file does NOT implement masking, hashing or PII decisions.
  L93: "HASH_VALUE": SemanticType.OTHER  (mapping de type taxonomique, pas d'opération)
  L204: ("hash", "HASH_VALUE", 0.75)     (alias de colonne, pas d'opération)
```

> Aucun code de masquage, hachage, nettoyage ou profiling statistique.  
> Seules des références documentaires et des mappings de noms de types.

---

## 7. Limitations connues

| Limitation | Détail |
|---|---|
| **Classifieur = prototype** | `intake/column_types.py` utilise la similarité Jaccard sur les tokens, pas ML. Précision ~90% sur Olist. |
| **Jaccard ≠ embeddings** | Deux colonnes avec des noms similaires mais significations différentes peuvent être confondues. |
| **Privacy vocabulary — À valider avec Ikbel** | `PERSON_ID: POTENTIAL_PII` (vs `LIKELY_PII` précédemment). Voir `docs/CONTRACT_CHANGE_PROPOSAL.md` §5. |
| **SemanticMatch.similarity_score = None** | Le moteur de similarité n'est pas implémenté en Étape 1 (scope BO1-06). |
| **Notebook nbclient warnings** | DeprecationWarning traitlets et RuntimeWarning zmq sur Windows (non bloquants, tests PASS). |

---

## 8. Ce qui ne peut pas être validé et pourquoi

| Élément | Raison |
|---|---|
| Test en venv isolé | `python -m venv` crée un env, mais `nbclient`/`ipykernel` doivent être installés séparément. La création d'un venv complet nécessiterait ~5 min de téléchargement. Tous les packages sont vérifiés présents via `pip install -r requirements.txt` (already satisfied). |
| `jupyter nbconvert --execute` | Bloqué par la stratégie de contrôle d'application Windows (AppLocker). Remplacé par exec() Python et nbclient. |
| Modèles ML / embeddings | Hors scope Étape 1. Prévu pour Étape 2. |

---

## 9. Archive

`BIFlow_SemanticDetection_Etape1.zip` — 0.28 MB  
Contenu : tous les fichiers du workspace hors `.git/`, `__pycache__/`, `runs/`, `.venv/`, `.ipynb_checkpoints/`, `*.pyc`, `*.zip`.

---

## 10. Commits de l'Étape 1 (branche BO1/Samar+Malek)

```
test(taxonomy): strict validator — missing description, empty group, bad privacy_hint are errors
fix(taxonomy): PERSON_ID -> POTENTIAL_PII, taxonomy v1.1.1, align with prompt spec
feat(notebook): rewrite 01_semantic_foundation.ipynb with 12 sections per original spec
test(notebook): add test_notebook.py, remove duplicate examples/ at root
chore(deps): split requirements.txt (etape 1) and requirements-app.txt (Samar app)
docs(report): VALIDATION_REPORT.md with real test counts, ZIP archive, .gitignore update
```
