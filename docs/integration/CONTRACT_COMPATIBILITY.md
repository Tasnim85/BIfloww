# BIFlow — Compatibilité et Harmonisation des Contrats

Ce document expose les principes d'harmonisation des contrats Pydantic v2 adoptés pour l'intégration globale de BIFlow sur la branche `fix/final-agent-integration-validation`.

---

## 1. Contexte des Divergences de Versions

Au cours du développement multi-équipes :
- Les équipes amont (BO1/BO4) ont stabilisé les contrats partagés sous la version `1.6` (notamment pour `common.py`, `agent.py`, `pipeline.py`, `intake.py`, `semantic.py`, `comparisons.py`, `xai.py`, `audit.py`).
- L'équipe BO2 (Ahmed & Ikbel) a développé initialement sur une version antérieure `1.1` en utilisant un wrapper adaptateur `bo2/contract_adapter.py`.
- L'équipe Rabeb a introduit des contrats analytiques enrichis (`analysis.py` avec multi-validations et support parquet).
- L'équipe Malek a conçu une proposition sémantique hiérarchique détaillée (`contracts/proposals/semantic_contracts.py`).

### Décision Fondamentale
**Le répertoire canonique `contracts/` de la branche d'intégration n'a pas été écrasé.** 
L'harmonisation s'appuie sur la préservation intégrale des contrats de référence v1.6 enrichis des adaptateurs structurels.

---

## 2. Table de Compatibilité des Schémas et Contrats

| Contrat | Version Active | Schéma Pydantic v2 | Consommateurs Réels | Décision de Compatibilité |
|---|---|---|---|---|
| `contracts/common.py` | 1.6 | `Contract`, `Artifact`, `Period`, `SemanticType`, `PrivacyHint` | Tous les agents | Rétro-compatibilité assurée ; validation stricte des champs inconnus (`extra="forbid"`). |
| `contracts/agent.py` | 1.6 | `RunContext`, `AgentResult`, `AgentStatus` | Tous les agents | Standardisation sur 4 statuts : `SUCCESS`, `FAILED`, `NEEDS_REVIEW`, `SKIPPED`. |
| `contracts/pipeline.py` | 1.6 | `Step`, `graph()`, `execution_order()` | Orchestrateur DAG | Sorties duales intégrées pour `similarity` et `column_types` ; précédence de `similarity` sur les étapes sémantiques. |
| `contracts/intake.py` | 1.6 | `Upload`, `SimilarityReport`, `ColumnTypesReport` | Upload, Similarity, Column Types, PII | Format officiel partagé par l'ensemble des agents consommateurs. |
| `contracts/proposals/semantic_contracts.py` | 1.0 (Extension) | `SemanticColumn`, `SemanticMetadata`, `SemanticMatchesReport` | Column Types, Similarity, Audit | Contrats enrichis émis conjointement avec les contrats standards (`semantic_metadata.json`, `column_matches.json`). |
| `contracts/privacy.py` | 1.6 | `PiiReport`, `PiiColumn`, `PiiKind`, `PiiAction` | PII, Profiling, Cleaning | Mappé automatiquement depuis la sortie interne BO2 par `bo2/contract_adapter.py`. |
| `contracts/quality.py` | 1.6 | `ProfileReport`, `CoverageProfile`, `AnomalyReport`, `CleaningReport` | Profiling, Cleaning, Comparisons | Exporté par l'adaptateur sans altération de la granularité temporelle ni des métriques. |
| `contracts/warehouse.py` | 1.6 | `WarehouseManifest`, `TransformationReceipts`, `LineageGraph` | ETL, Lineage, Analysis, Comparisons | Schéma des vues analytiques et graphe de lignage alignés sur le KPI Catalog. |
| `contracts/semantic.py` | 1.6 | `AnalysisRequest`, `Glossary`, `KpiCatalog` | Request, Analysis, Comparisons | Support complet des filtres, dimensions multiples, périodes de comparaison et synonymes multilingues. |
| `contracts/analysis.py` | 1.6 | `AnalysisResult`, `ValidationCheck` | Analysis, Comparisons, Dashboard | Contrat enrichi supportant les validations numériques et le dataframe de données `result.parquet`. |
| `contracts/comparisons.py` | 1.6 | `ComparisonReport`, `ComparisonCheck`, `ProposedFix` | Comparisons, Dashboard | Support des avertissements d'incomplétude temporelle et des propositions de dates complètes. |
| `contracts/dashboard.py` | 1.6 | `DashboardSpec`, `ChartSpec`, `KpiCard` | Dashboard, Streamlit, Web Next.js | Support multi-graphiques (barres groupées, séries temporelles, KPI cards) et localisation. |
| `contracts/audit.py` | 1.6 | `AuditEvent`, `IntegrityReport`, `DEFAULT_JOURNAL` | Orchestrateur, Auditor, Dashboard | Journal immuable avec hachage SHA-256 en chaîne, détection de falsification et accès concurrent sûr. |

---

## 3. Mécanisme de Publication et Adaptateurs

L'adaptateur `bo2/contract_adapter.py` assure la conversion transparente entre les structures de travail internes des agents BO2 et les contrats d'équipe standardisés :

```text
Sortie brute de l'agent (JSON non validé)
               |
               v
      details_path(path) (sauvegarde privée des métadonnées)
               |
               v
      Validation Pydantic v2 (PiiReport, ProfileReport, etc.)
               |
               v
  Publication atomique dans runs/<run_id>/<step>/<filename>.json
```

Ce motif garantit :
1. Qu'aucun artefact publié ne viole son contrat Pydantic.
2. Qu'aucun agent aval ne reçoit de données partielles ou corrompues.
3. Que les 18 exemples JSON de référence demeurent rigoureusement conformes (`python -m contracts.check_contracts` validé à 100%).
