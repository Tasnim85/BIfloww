# Analyse d'intégration — Step 2 Rule-Based Classifier

**Document :** `docs/STEP2_INTEGRATION_ANALYSIS.md`
**Date :** 2026-10-21
**Auteur :** Audit technique BIFlow (branche `fix/biflow-audit-findings`)
**Branche analysée :** `feature/semantic-detection-step2-rule-based` @ `53e5fd9`

---

## 1. Contexte

La branche B (`feature/semantic-detection-step2-rule-based`) contient un second
classificateur sémantique pour les colonnes. Ce document compare son architecture
à celle de l'étape 1 (déjà intégrée dans `BO1/Samar+Malek`) et recommande une
stratégie d'intégration.

---

## 2. Architecture comparée

| Critère | Étape 1 (`intake/column_types.py`) | Étape 2 (`step2/rule_classifier.py`) |
|---------|-------------------------------------|--------------------------------------|
| **Entrée** | CSV brut — headers uniquement | `ColumnSchema` (nom + dtype + échantillon optionnel) |
| **Taxonomie** | Même `semantic_types.yaml` (TaxonomyLoader) | Même `semantic_types.yaml` + `classification_rules.yaml` |
| **Méthodes** | 1. Alias exact → 2. Mot-clé → 3. Repli UNKNOWN | 1. Alias exact (0.95) → 2. Règle YAML keyword (conf. YAML) → 3. Pattern regex valeurs → 4. Contextuel table → 5. UNKNOWN |
| **Confiance** | Fixe par tier (0.95 / 0.80 / 0.00) | Par règle YAML (personnalisable par type) |
| **Valeurs** | Non utilisées | Optionnelles (patterns regex sur échantillon) |
| **Contexte** | Aucun | Table voisine, colonnes adjacentes (tier 4) |
| **Output** | `ColumnTypesReport` (contracts.intake) | `ClassificationResult` (dataclass locale) |
| **Contrats Pydantic** | Oui — validés à la sortie | Non — dataclass interne, pas de contrat Pydantic |
| **Fichiers** | 1 fichier | 5 fichiers (`rule_classifier`, `schema_reader`, `name_normalizer`, `ambiguity_handler`, `pipeline`) |

---

## 3. Colonnes Olist testées (comparaison des deux étapes)

Test réalisé sur les colonnes du fichier `data/sample/olist_orders_dataset.csv` :

| Colonne | Étape 1 | Étape 2 (attendu) | Verdict |
|---------|---------|-------------------|---------|
| `order_id` | ORDER_ID (BUSINESS_ENTITY_DATA) | ORDER_ID | ✅ Cohérent |
| `customer_id` | PERSON_ID (PERSONAL_DATA) | PERSON_ID | ✅ Cohérent |
| `order_status` | STATUS (CATEGORICAL_DATA) | STATUS | ✅ Cohérent |
| `order_purchase_timestamp` | DATETIME (TEMPORAL_DATA) | DATETIME | ✅ Cohérent |
| `order_approved_at` | DATETIME (TEMPORAL_DATA) | DATETIME | ✅ Cohérent |
| `order_delivered_customer_date` | DATETIME (TEMPORAL_DATA) | DATETIME | ✅ Cohérent |
| `order_estimated_delivery_date` | DATE (TEMPORAL_DATA) | DATE | ✅ Cohérent |

> **Note :** L'étape 2 n'a pas été exécutée directement (dépendance à
> `classification_rules.yaml` absent de la branche B). Les résultats de
> l'étape 2 sont déduits de l'architecture (alias YAML identiques).

---

## 4. Analyse des différences clés

### 4.1 Niveau de confiance plus fin (Step 2 ✅)
Step 2 permet de définir une confiance par règle dans `classification_rules.yaml`.
Step 1 utilise des paliers fixes (0.95 / 0.80 / 0.00). Step 2 est supérieure pour
les cas ambigus (ex. `freight_value` : confiance 0.90 vs 0.80).

### 4.2 Utilisation des valeurs (Step 2 ✅)
Step 2 peut appliquer des patterns regex sur un échantillon de valeurs, ce qui
permet de discriminer `postal_code` (regex `^[0-9]{5}$`) de `quantity` (regex
`^[0-9]{1,4}$`) quand le nom seul est ambigu.

### 4.3 Détection contextuelle (Step 2 ✅)
Step 2 ajoute un tier 4 contextuel : si une table s'appelle `dim_customer`, les
colonnes `id` non résolues sont promues en PERSON_ID. Step 1 n'a pas ce mécanisme.

### 4.4 Output non conforme aux contrats (Step 2 ⚠️)
Step 2 retourne un `ClassificationResult` (dataclass Python), pas un `ColumnType`
Pydantic. L'orchestrateur attend un `ColumnTypesReport` en sortie de step
`column_types`. Une couche d'adaptation est nécessaire.

### 4.5 Pas d'entrypoint DAG (Step 2 ⚠️)
La branche B ne contient pas de fonction `run(ctx: RunContext) -> AgentResult`.
Elle ne peut pas être invoquée directement par l'orchestrateur.

---

## 5. Décision recommandée

**Recommandation : intégrer step 2 comme étape distincte `column_types_v2`
en parallèle de `column_types` (step 1), avec une phase de comparaison.**

Raisons :
1. Step 2 est **complémentaire**, pas un remplacement — elle ajoute les patterns
   valeurs et le contexte, mais ne casse pas les classifications step 1.
2. L'output step 2 doit être adapté en `ColumnTypesReport` (une couche wrapper
   de ~30 lignes suffit).
3. Les 199 tests de la branche B passent indépendamment — les fusionner dans
   `BO1/Samar+Malek` sans couche d'adaptation provoquerait une régression.
4. La fusion directe (`git merge`) est sans conflit (vérifié : 0 conflits sur
   `biflow-merge-test`), mais les fichiers step 2 manquent de `run(ctx)` et
   de `classification_rules.yaml`.

**Plan d'intégration (non implémenté dans ce commit — scope futur) :**

```
contracts/pipeline.py  → ajouter Step(name="column_types_v2", ...)
intake/column_types_v2.py → wrapper appelant step2/pipeline.py
                            + adapter ClassificationResult -> ColumnType
intake/semantic_detection/config/classification_rules.yaml → créer
```

**Ce qui est EXCLU :** fusion immédiate, modification de `contracts/pipeline.py`
dans ce commit (risque de régression pour les autres agents).

---

## 6. Statut

| Point | Statut |
|-------|--------|
| Analyse architecture step 1 vs step 2 | ✅ Complète |
| Test colonnes Olist step 1 | ✅ Exécuté (117 tests passent) |
| Test colonnes Olist step 2 | ⏳ Non exécuté (classification_rules.yaml absent) |
| Fusion branche B dans fix branch | ❌ Non fait (recommandation : étape séparée) |
| Simulation merge sans conflit | ✅ Vérifié sur biflow-merge-test |
