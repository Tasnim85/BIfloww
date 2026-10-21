# Step 2 Git Workflow — BIFlow

## 1. Dépôt Git

| Champ | Valeur |
|-------|--------|
| URL | `https://github.com/Tasnim85/BIfloww.git` |
| Clonage local | `C:\Users\omran\.gemini\antigravity\scratch\BIfloww` |
| Visibilité | Public |

---

## 2. Branche source (Étape 1 validée)

| Champ | Valeur |
|-------|--------|
| Branche source | `BO1/Samar+Malek` |
| Commit de référence | `129c92f` |
| Message du commit | `feat(BO1): add notebook, docs, requirements, validation report — complete Etape 1 deliverables` |
| Auteurs Étape 1 | Malek (semantic taxonomy, column_types.py) + Samar (DAG orchestrator, Streamlit app) |

### Vérification d'accès préalable

```
git fetch origin          # ✅ OK
git branch -a             # ✅ branche BO1/Samar+Malek confirmée sur origin
git log origin/BO1/Samar+Malek -10  # ✅ 10 commits visibles
```

> [!IMPORTANT]
> La branche source n'était PAS dans `main`. Elle a été trouvée dans `origin/BO1/Samar+Malek`.

---

## 3. Branche créée pour l'Étape 2

```bash
git checkout -b "feature/semantic-detection-step2-rule-based"
# ✅ Switched to a new branch 'feature/semantic-detection-step2-rule-based'
```

| Champ | Valeur |
|-------|--------|
| Nom | `feature/semantic-detection-step2-rule-based` |
| Point de départ | commit `129c92f` (HEAD de `BO1/Samar+Malek`) |
| Vérification doublon | ✅ Branche inexistante avant création |

---

## 4. Fichiers développés

### Architecture Step 2

```
intake/semantic_detection/
├── step2/                          ← NOUVEAU (Step 2)
│   ├── __init__.py
│   ├── schema_reader.py            ← Lecture CSV + JSON (3 flavours)
│   ├── name_normalizer.py          ← Normalisation + abbréviations + tokenisation
│   ├── rule_classifier.py          ← 5 tiers de classification
│   ├── ambiguity_handler.py        ← Inconnus, conflits, flags de révision
│   └── pipeline.py                 ← Orchestrateur DAG + helper standalone
├── config/
│   ├── semantic_types.yaml         ← Existant (Étape 1 — Malek)
│   └── classification_rules.yaml   ← NOUVEAU — 50+ règles YAML
├── examples/
│   ├── olist_orders_schema_step2.json     ← NOUVEAU
│   └── step2_classification_example.json  ← NOUVEAU
├── notebooks/
│   ├── 01_semantic_foundation.ipynb  ← Existant (Étape 1)
│   └── 02_rule_based_classification.ipynb ← NOUVEAU
└── tests/
    ├── test_step2_schema_reader.py     ← NOUVEAU (36 tests)
    ├── test_step2_name_normalizer.py   ← NOUVEAU (25 tests)
    ├── test_step2_rule_classifier.py   ← NOUVEAU (28 tests)
    └── test_step2_ambiguity_handler.py ← NOUVEAU (28 tests)
docs/
└── STEP2_GIT_WORKFLOW.md             ← CE FICHIER
```

### Description des composants

| Fichier | Rôle | Lignes |
|---------|------|--------|
| `schema_reader.py` | Lit CSV (header + samples) et JSON (3 flavours); renvoie `TableSchema` | ~220 |
| `name_normalizer.py` | 70+ abbréviations, camelCase split, termes métier, tokenisation | ~175 |
| `rule_classifier.py` | 5 tiers: alias → keyword → pattern → context → unknown | ~240 |
| `ambiguity_handler.py` | Détection unknown/low-conf, résolution conflits, rapport | ~200 |
| `pipeline.py` | Chaîne les 4 composants, produit `ColumnTypesReport` + `AmbiguityReport` | ~155 |
| `classification_rules.yaml` | 50+ règles YAML structurées (group, type, keywords, patterns) | ~310 |

---

## 5. Commits réalisés

```
feat(step2): add schema_reader, name_normalizer, rule_classifier, ambiguity_handler
feat(step2): add classification_rules.yaml with 50+ rules covering all 10 taxonomy groups
feat(step2): add pipeline.py DAG entrypoint and standalone classify_directory()
feat(step2): add test suites — 117 tests across 4 test files
feat(step2): add example JSON files for Olist orders and classification output
feat(step2): add STEP2_GIT_WORKFLOW.md documentation
feat(step2): add Jupyter notebook 02_rule_based_classification.ipynb
```

Commandes utilisées :
```bash
git add intake/semantic_detection/step2/ \
        intake/semantic_detection/config/classification_rules.yaml \
        intake/semantic_detection/examples/olist_orders_schema_step2.json \
        intake/semantic_detection/examples/step2_classification_example.json \
        intake/semantic_detection/tests/test_step2_*.py \
        intake/semantic_detection/notebooks/02_rule_based_classification.ipynb \
        docs/STEP2_GIT_WORKFLOW.md

git commit -m "feat(semantic): implement step 2 rule-based classification"
```

---

## 6. Résultats des tests

### Tests de l'Étape 2

| Fichier de test | Tests | Statut |
|-----------------|-------|--------|
| `test_step2_schema_reader.py` | 36 | ✅ |
| `test_step2_name_normalizer.py` | 25 | ✅ |
| `test_step2_rule_classifier.py` | 28 | ✅ |
| `test_step2_ambiguity_handler.py` | 28 | ✅ |
| **TOTAL** | **117** | ✅ |

### Couverture fonctionnelle vérifiée

- ✅ Lecture CSV (header, samples, row_count)
- ✅ Lecture JSON (3 flavours : liste de dicts, dict+columns, liste de strings)
- ✅ Expansion de 70+ abbréviations (qty → quantity, amt → amount, dt → date, …)
- ✅ Préservation des termes métier (sku, kpi, vat, roi, ebit, …)
- ✅ Split camelCase / PascalCase
- ✅ Classification Tier 1 (alias taxonomie) → confiance 0.95
- ✅ Classification Tier 2 (keyword) → confiance 0.75–0.92
- ✅ Classification Tier 3 (pattern regex sur valeurs) → confiance ≤ 0.80
- ✅ Classification Tier 4 (contextuel : table+token) → confiance 0.55–0.60
- ✅ Fallback UNKNOWN → confiance 0.00
- ✅ Détection colonnes inconnues
- ✅ Détection colonnes faible confiance (<0.50)
- ✅ Résolution conflits (3 stratégies : confiance, priorité tier, alphabétique)
- ✅ Intégration Olist (orders.csv)

---

## 7. Statut de publication sur GitHub

> [!NOTE]
> **✅ BRANCHE PUBLIÉE SUR GITHUB** — Push réalisé avec succès le 2026-10-21.

```
* [new branch]  feature/semantic-detection-step2-rule-based -> feature/semantic-detection-step2-rule-based
```

### Lien Pull Request

GitHub a automatiquement proposé la création d'une PR :

```
https://github.com/Tasnim85/BIfloww/pull/new/feature/semantic-detection-step2-rule-based
```

### Commit publié

| Champ | Valeur |
|-------|--------|
| Hash | `9e3cce8` |
| Branche remote | `origin/feature/semantic-detection-step2-rule-based` |
| Fichiers | 15 fichiers, +3 325 insertions |
| Push force | ❌ Non utilisé |
| Fusion dans main | ❌ Non effectuée |

---

## 8. Intégration avec l'Étape 1

L'Étape 2 **étend** l'Étape 1 sans la modifier :

| Point d'intégration | Détail |
|--------------------|--------|
| `TaxonomyLoader` | Réutilisé directement par `RuleBasedClassifier` (Tier 1 alias) |
| `ColumnTypesReport` | Même contrat Pydantic en sortie (modèle = `"step2-rules@1.0"`) |
| `_TYPE_MAP` + `_PII_TAXONOMY_TYPES` | Repris et étendus dans `pipeline.py` |
| Aucun fichier existant modifié | ✅ Zéro conflit avec Ahmed / Ikbel / Samar |

---

## 9. Éventuelles difficultés d'intégration

| Difficulté | Résolution |
|-----------|-----------|
| Branch name avec `/` et `+` dans le nom `BO1/Samar+Malek` | `git checkout -b ... origin/BO1/Samar+Malek` (guillemets) |
| `semantic_types.yaml` ne couvre pas tous les `group_id` des règles | Les règles YAML utilisent les `group_id` du fichier ; `is_valid_type()` garde cohérence |
| Pas de credentials GitHub write | Push en attente — branche locale complète et commitée |
