# Proposition d'Intégration — Step 2 Rule-Based Classifier (Branche B)

**Document :** `docs/STEP2_INTEGRATION_PROPOSAL.md`  
**Date :** 2026-10-21  
**Auteurs :** Samar & Malek (Audit et intégration technique)  
**Branche source :** `feature/semantic-detection-step2-rule-based` (`53e5fd9`)  
**Branche cible :** `fix/biflow-audit-findings` (`BO1/Samar+Malek`)  

---

## 1. Inspection de la Branche B

### 1.1 Fichiers et Architecture
La branche B implémente un classificateur sémantique par règles à 5 niveaux de priorité :
- `intake/semantic_detection/config/classification_rules.yaml` : **518 lignes de règles** YAML réparties par priorité (1 à 10) avec mots-clés, patterns regex de valeurs et indices contextuels par table.
- `intake/semantic_detection/step2/rule_classifier.py` : moteur d'inférence (Tier 1: Alias exact 0.95 -> Tier 2: Mots-clés règles -> Tier 3: Regex sur valeurs d'échantillons -> Tier 4: Contexte de table -> Tier 5: Repli UNKNOWN).
- `intake/semantic_detection/step2/ambiguity_handler.py` : détection d'ambiguïté (écart de confiance < 0.15) et génération d'`AmbiguityReport`.
- `intake/semantic_detection/step2/pipeline.py` : point d'entrée avec fonction `run(ctx: RunContext) -> AgentResult` produisant `ColumnTypesReport` et `ambiguity_report.json`.

### 1.2 Tests
- 30 tests unitaires dans `test_step2_rule_classifier.py` : **30/30 PASS** (0 échec).

---

## 2. Comparaison Expérimentale : Step 1a vs Step 2

Exécution comparative réelle sur les **8 tables Olist** (50 colonnes analysées) via `compare_step1_step2.py` :

| Métrique | Valeur |
|----------|--------|
| Colonnes totales analysées | 50 |
| Concordance exacte | 43 / 50 (**86.0%**) |
| Divergences constatées | 7 / 50 (14.0%) |

### Analyse des 7 divergences

| Table.Colonne | Step 1a | Step 2 (Branche B) | Cause racine & Analyse |
|---------------|---------|--------------------|------------------------|
| `customers.customer_unique_id` | `ID (PII=True)` | `ID (PII=False)` | Step 2 classé `SYSTEM_ID` -> PII false. **Step 1a est plus sûr** (un identifiant client est PII). |
| `order_items.order_item_id` | `ID (PII=False)` | `QUANTITY (PII=False)` | Step 2 utilise l'alias `QUANTITY`. Le prompt d'audit attend `ID` (numéro séquentiel de ligne). |
| `payments.payment_sequential` | `NUMBER (PII=False)` | `QUANTITY (PII=False)` | Divergence sémantique mineure (rang vs quantité). |
| `payments.payment_installments` | `QUANTITY (PII=False)` | `NUMBER (PII=True)` | **Faux positif PII dans Step 2** : la regex de valeur a classé un nombre d'échéances comme PII. |
| `reviews.review_id` | `ID (PII=False)` | `TEXT (PII=True)` | **Faux positif PII dans Step 2** : le mot-clé "review" a pris le dessus sur "_id". |
| `orders.order_estimated_delivery_date` | `DATE` | `DATETIME` | Différence mineure d'alias temporalité. |
| `products.product_photos_qty` | `QUANTITY` | `NUMBER` | Différence mineure (QUANTITY vs NUMERIC_MEASURE). |

---

## 3. Stratégie d'Intégration Recommandée

### 3.1 Pourquoi ne pas écraser Step 1a ?
1. **Contrats stricts et tests d'équipe :** Step 1a satisfait à 100% les 28 tests golden du projet BIFlow (`test_olist_columns.py`), notamment la classification de `order_item_id` en ID et l'absence de faux positifs PII sur `review_id` et `payment_installments`.
2. **Risque de régression PII :** Step 2 introduit 2 faux positifs PII (`review_id`, `payment_installments`) et 1 faux négatif (`customer_unique_id`).

### 3.2 Modalité d'Intégration Sans Écrasement
1. **Étape DAG distincte `column_types_v2` :**
   - Conserver l'étape 1a `column_types` comme étape de production par défaut écrivant dans `runs/<run_id>/column_types/column_types.json`.
   - Ajouter l'étape `column_types_v2` dans `contracts/pipeline.py` écrivant dans `runs/<run_id>/column_types_v2/` (`column_types.json` et `ambiguity_report.json`).
   - Aucun écrasement d'artefacts entre les deux moteurs.
2. **Ajustement préalable des règles de Step 2 avant mise en production :**
   - Ajouter une règle prioritaire `ID_OVER_TEXT_RULE` pour les colonnes se terminant par `_id` (`review_id`).
   - Corriger `payment_installments` pour lui assigner `QUANTITY` (PII=False).
   - Assigner `PII=True` à `customer_unique_id`.
