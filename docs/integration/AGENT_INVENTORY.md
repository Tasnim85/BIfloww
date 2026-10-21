# BIFlow — Inventaire Réel des Agents et Composants

Ce document détaille l'audit technique exhaustif de l'intégralité des agents du projet BIFlow intégrés sur la branche `fix/final-agent-integration-validation`.

---

## 1. Matrice Globale de Qualification des Agents

| Agent | Responsabilité & Propriétaire | Entrypoint DAG | Statut Réel | Modèle / Backend | Validation Établie |
|---|---|---|---|---|---|
| **upload** | Réception et ingestion CSV multi-tables (Samar) | `app.upload:run` | **Opérationnel** | Python I/O, pandas | Validé isolément & dans le DAG (9 tables Olist) |
| **similarity** | Détection de dataset & matching colonnes bijectif hongrois (Malek) | `intake.similarity:run` | **Opérationnel** | `scipy.optimize.linear_sum_assignment`, SentenceTransformers / TF-IDF | Validé isolément, tests golden & E2E (produit `similarity_report.json` + `column_matches.json`) |
| **column_types** | Classification sémantique 5 tiers + Arbitre Hybride (Malek) | `intake.column_types:run` | **Opérationnel** | Moteur de règles (518 lignes YAML) + HybridClassifier (TF-IDF / MiniLM) | Validé isolément, 39/39 colonnes Olist golden & E2E (produit `column_types.json` + `semantic_metadata.json`) |
| **request** | Compréhension NL de la demande métier, KPI & temporalité (Malek) | `semantic.request:run` | **Opérationnel** | Parser déterministe, synonymes multilingues, SentenceTransformers / TF-IDF | Validé isolément & E2E (produit `analysis_request.json`, déclenche `NEEDS_REVIEW` si inconnu) |
| **pii** | Détection PII par Llama 3 & masquage HMAC (Ikbel) | `privacy.pii:run` | **Opérationnel avec prérequis** | Local Ollama (`llama3:latest`), secret `BO2_PII_SECRET` (32 chars) | Validé avec Ollama et stubs E2E. En l'absence d'Ollama, bloque strictement le DAG aval. |
| **profiling** | Profilage statistique, complétude & anomalies (Ahmed) | `profiling.profiler:run` | **Opérationnel** | scikit-learn (`IsolationForest`), pyarrow, pandas | Validé isolément & E2E (produit `profile_report.json`, `coverage_profile.json`, `anomaly_scores.parquet`) |
| **cleaning** | Application des règles de playbook d'assainissement (Ikbel) | `cleaning.cleaner:run` | **Opérationnel** | Playbooks YAML (`olist@1.3.yaml`) + adaptations contractuelles | Validé isolément & E2E (produit `cleaning_report.json` + tables nettoyées) |
| **etl** | Construction de l'entrepôt analytique DuckDB & Manifeste (Ahmed) | `etl.build:run` | **Opérationnel** | DuckDB in-process engine, pyarrow | Validé isolément & E2E (produit `warehouse.duckdb`, `warehouse_manifest.json`, `receipts.json`) |
| **analysis** | Compilation SQL, exécution KPI & validation des grains (Rabeb) | `analysis.analyst:run` | **Opérationnel** | DuckDB SQL compiler, KPI Catalog (`Revenue@2.0`, `AverageBasket@2.0`) | Validé isolément, tests SQL, tests d'API et validation E2E (produit `analysis_result.json`, `result.parquet`) |
| **comparisons** | Contrôle de comparabilité temporelle & alertes de drift (Tasnim) | `comparisons.checker:run` | **Opérationnel** | Moteur de règles comparatives, analyse des périodes incomplètes | Validé isolément & E2E (produit `comparison_report.json`, gestion `NEEDS_REVIEW` sur mois tronqué) |
| **dashboard** | Génération de la spécification visuelle et KPI cards (Samar) | `app.dashboard:run` | **Opérationnel** | Spécificateur visuel, Vega/Altair mapping | Validé isolément & E2E (produit `dashboard_spec.json`) |
| **lineage** | Graphe de lignage de bout en bout des métriques (Ahmed) | `etl.lineage:run` | **Opérationnel** | JSON DAG / Neo4j driver | Validé isolément & E2E (produit `lineage.json`) |
| **auditor** | Vérification d'intégrité cryptographique du journal & XAI (Tasnim) | `auditor.agent:run` | **Opérationnel** | SHA-256 HMAC journal check, SHAP explainer | Validé isolément & E2E (produit `explanations.json`, `drift_report.json`, `integrity_report.json`) |

---

## 2. Inventaire Détaillé par Composant

### 2.1. Upload (`app.upload`)
- **Fichier :** `app/upload.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `ctx.params["source_dir"]`
- **Sorties :** `upload.json` (contrat `contracts.intake.Upload`), `tables/` (répertoire des CSV bruts).
- **Contrôles :** Non-vide, présence des CSV, taille non nulle.

### 2.2. Similarity (`intake.similarity`)
- **Fichier :** `intake/similarity.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `upload.upload`, `upload.tables`
- **Sorties :** `similarity_report.json` (contrat `contracts.intake.SimilarityReport`), `column_matches.json` (contrat `SemanticMatchesReport`).
- **Algorithme :** Affectation globale par matrice de similarité complète via la méthode hongroise `scipy.optimize.linear_sum_assignment`. Backend SentenceTransformers `all-MiniLM-L6-v2` avec repli déterministe TF-IDF / lexical.
- **Différenciation :** Homonymes inter-tables non confondus (`customers.id` vs `products.id`).

### 2.3. Column Classification (`intake.column_types`)
- **Fichier :** `intake/column_types.py`
- **Packages sous-jacents :** `intake/semantic_detection/step2/` (moteur de règles 5 tiers), `intake/semantic_detection/step3/` (`HybridClassifier`).
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `upload.tables`
- **Sorties :** `column_types.json` (`ColumnTypesReport`), `semantic_metadata.json` (`SemanticMetadata`).
- **Comportement :** Lecture dynamique de `taxonomy_version` depuis `config/semantic_types.yaml`, respect strict du périmètre Privacy (aucune valeur PII brute dans les métadonnées).

### 2.4. Request Understanding (`semantic.request`)
- **Fichier :** `semantic/request.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `upload.upload`, `static:semantic/glossary.yaml`, `static:kpi/catalog.yaml`
- **Sorties :** `analysis_request.json` (`AnalysisRequest`).
- **Comportement :** Détection de KPI, dimensions, période calendaire complète. Si le KPI est inconnu ou ambigu, retourne `AgentStatus.NEEDS_REVIEW` sans inventer de métrique.

### 2.5. Privacy & Masking (`privacy.pii`)
- **Fichier :** `privacy/pii.py` & `privacy/agent.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `upload.tables`, `column_types.report`
- **Sorties :** `pii_report.json` (`PiiReport`), `tables/` (fichiers Parquet masqués).
- **Prérequis :** Variable `BO2_PII_SECRET` (>= 32 caractères) chargée via `.env` et serveur local Ollama avec modèle Llama 3. Si Ollama est absent, échoue proprement et bloque la chaîne aval.

### 2.6. Profiling & Anomalies (`profiling.profiler`)
- **Fichier :** `profiling/profiler.py` & `profiling/agent.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `pii.tables`, `column_types.report`
- **Sorties :** `profile_report.json` (`ProfileReport`), `coverage_profile.json` (`CoverageProfile`), `anomaly_report.json` (`AnomalyReport`), `anomaly_model.joblib`, `anomaly_scores.parquet`.
- **Validation :** Contrôle Parquet obligatoire sur `anomaly_scores.parquet` (en-tête `PAR1`).

### 2.7. Data Cleaning (`cleaning.cleaner`)
- **Fichier :** `cleaning/cleaner.py` & `cleaning/agent.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `pii.tables`, `profiling.profile`, `similarity.report`, `column_types.report`, `static:cleaning/playbooks`
- **Sorties :** `cleaning_report.json` (`CleaningReport`), `tables/` (Parquet nettoyés).
- **Validation :** Application des règles déterministes de playbook (`olist@1.3.yaml`).

### 2.8. ETL & Entrepot Analytique (`etl.build`)
- **Fichier :** `etl/agent.py` & `etl/build.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `cleaning.tables`
- **Sorties :** `warehouse.duckdb` (base DuckDB), `warehouse_manifest.json` (`WarehouseManifest`), `receipts.json` (`TransformationReceipts`).
- **Validation :** Drain systématique des curseurs DuckDB (`fetchall`) pour éviter les conflits de verrous.

### 2.9. Analyst Agent (`analysis.analyst`)
- **Fichier :** `analysis/analyst.py`, `analysis/sql_compiler.py`, `analysis/validations.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `request.request`, `etl.warehouse`, `etl.manifest`, `etl.receipts`, `static:kpi/catalog.yaml`
- **Sorties :** `analysis_result.json` (`AnalysisResult`), `result.parquet` (`DataFrame[customer_state, period, value]`).
- **Validation :** Vérification stricte des multi-grains, des ratios non-additifs et des totaux indépendants.

### 2.10. Comparisons Checker (`comparisons.checker`)
- **Fichier :** `comparisons/checker.py`, `comparisons/checks.py`, `comparisons/fix.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `request.request`, `analysis.result`, `profiling.coverage`, `etl.warehouse`, `etl.manifest`, `etl.receipts`, `static:kpi/catalog.yaml`
- **Sorties :** `comparison_report.json` (`ComparisonReport`).
- **Validation :** Détection d'incomplétude de période (août tronqué) -> émission `NEEDS_REVIEW` avec proposition de correction tronquée à la dernière date complète (2018-08-23).

### 2.11. Dashboard (`app.dashboard`)
- **Fichier :** `app/dashboard.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `request.request`, `analysis.result`, `analysis.data`, `comparisons.report`
- **Sorties :** `dashboard_spec.json` (`DashboardSpec`).
- **Validation :** Rendu des KPI cards, grouped bar charts multilingues.

### 2.12. Lineage (`etl.lineage`)
- **Fichier :** `etl/lineage.py`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `etl.receipts`, `etl.manifest`, `static:kpi/catalog.yaml`
- **Sorties :** `lineage.json` (`LineageGraph`).
- **Validation :** Traçabilité directe KPI -> Vues analytiques -> Tables de faits et dimensions.

### 2.13. Auditor & XAI (`auditor.agent`)
- **Fichier :** `auditor/agent.py`, `auditor/journals.py`, `auditor/xai/`
- **Interface :** `run(ctx: RunContext) -> AgentResult`
- **Entrées :** `profiling.anomalies`, `profiling.model`, `profiling.scores`, `lineage.graph`
- **Sorties :** `explanations.json` (`ExplanationReport`), `drift_report.json` (`DriftReport`), `integrity_report.json` (`IntegrityReport`).
- **Validation :** Vérification de chaîne de hachage SHA-256 du journal et détection de falsification.
