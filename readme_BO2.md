# BIFlow — BO2 : Ahmed et Ikbel

Ce guide décrit toutes les étapes BO2 disponibles dans **streamlit_BO2.py**, depuis les fichiers importés jusqu’au graphe de lignage.

## 1. Périmètre

| Responsable | Tâche | Module |
|---|---|---|
| Ikbel | Détection et masquage des informations personnelles | `privacy.pii:run` |
| Ahmed | Profilage, couverture et anomalies | `profiling.profiler:run` |
| Ikbel | Nettoyage par playbook versionné ou généré | `cleaning.cleaner:run` |
| Ahmed | Organisation et construction de l’entrepôt | `etl.build:run` |
| Ahmed | Lignage et enregistrement Neo4j | `etl.lineage` |

L’application est un banc de test BO2. Le DAG global, le catalogue KPI, les calculs, SHAP et le tableau de bord final nécessitent encore l’intégration des autres groupes.

## 2. Installation et lancement

Depuis PowerShell :

```powershell
cd "C:\Users\ikbel\Desktop\PI\BIfloww"
# Créer l’environnement seulement s’il n’existe pas déjà.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-streamlit.txt
.\.venv\Scripts\python.exe -m bo2 init-local
```

`requirements-streamlit.txt` inclut les dépendances BO2. `init-local` prépare le fichier `.env` sans afficher les secrets ni remplacer les valeurs existantes.

Ouvrir Ollama et Docker Desktop, puis :

```powershell
ollama list
# Uniquement si le modèle manque :
ollama pull llama3:latest

docker compose -f compose.neo4j.yml up -d
.\.venv\Scripts\python.exe -m streamlit run streamlit_BO2.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

Ouvrir **http://127.0.0.1:8501/**. Le lanceur existant `lancer_pii.cmd` démarre désormais la même application BO2. Pour arrêter le serveur, utiliser `Ctrl+C` dans son terminal.

Llama3 est appelé localement via Ollama. Neo4j est dédié au projet et conserve ses données dans les volumes Docker. Les identifiants et le secret de pseudonymisation restent dans `.env` ; ne pas publier ce fichier.

## 3. Ordre du parcours

1. Importer et protéger les fichiers.
2. Examiner la couverture des commandes et les valeurs inhabituelles.
3. Nettoyer les données et comparer avant/après.
4. Valider l’organisation proposée puis construire l’entrepôt.
5. Consulter et vérifier le lignage dans Neo4j.

Le profilage est un diagnostic des fichiers protégés. Il ne corrige pas les anomalies et n’est pas obligatoire avant le nettoyage. Le lignage est transversal, même si sa consultation est placée après l’entrepôt.

## 4. Protection des données — Ikbel

Déposer les fichiers CSV ou Parquet avec **Choisir mes fichiers**, puis cliquer sur **Lancer la protection**.

Llama3 classe les colonnes en distinguant informations personnelles, clés techniques et attributs métier. Il examine les noms, statistiques et de courts exemples transmis au serveur local. Selon leur catégorie, les informations personnelles sont pseudonymisées ou masquées ; les mesures et attributs métier peuvent être conservés. Un contrôle des contacts complète la classification.

L’interface affiche le bilan, les informations conservées et protégées, un aperçu et un téléchargement CSV. Les cas incertains peuvent être protégés par précaution ; les clés techniques incertaines peuvent bloquer la publication afin de préserver les relations. Vérifier les décisions pour chaque nouvelle structure.

Sorties : `pii/pii_report.json` et `pii/tables/*.parquet`. Le téléchargement contient les fichiers protégés et un bilan lisible, sans fichiers bruts.

## 5. Profilage et couverture des commandes — Ahmed

Dans **Comprendre mes données**, utiliser **Afficher le bilan des commandes**. Pour une autre structure, choisir le fichier, l’identifiant de commande, la date et le statut dans les réglages proposés.

Le bilan compte les commandes par jour, par statut et par combinaison jour/statut. Les dates et statuts absents ou invalides sont distingués. Un identifiant sélectionné doit être unique ; sans identifiant, chaque ligne est explicitement comptée comme une commande.

Sorties :

- `profiling/profile_report.json` : volumes, valeurs absentes, cardinalités, doublons et empreintes des fichiers.
- `profiling/coverage_profile.json` : répartition des commandes et contrôles des totaux.

Les réglages initiaux correspondent au dataset du projet. Pour une autre source, adapter les correspondances ; cette analyse suppose que les données représentent des commandes.

## 6. Détection d’anomalies et préparation SHAP — Ahmed

Dans **Valeurs inhabituelles**, choisir les variables numériques puis cliquer sur **Rechercher les valeurs inhabituelles**.

Le modèle combine un remplacement des valeurs absentes par la médiane avec une **Isolation Forest** : 100 arbres, graine 42 et proportion indicative de 1 % par défaut. Les colonnes protégées et les identifiants sont exclus des variables. Les valeurs absentes ou invalides sont également signalées.

Cette tâche **détecte sans corriger ni supprimer les lignes**. Une anomalie est un élément à vérifier, pas une preuve d’erreur ou de fraude. Pour une autre dataset, choisir les variables adaptées : le modèle est entraîné sur les données sélectionnées.

Sorties :

- `profiling/anomaly_model.joblib` : pipeline entraîné.
- `profiling/anomaly_scores.parquet` : scores, lignes concernées et variables préparées.
- `profiling/anomaly_report.json` : paramètres, contrôles, ordre des variables et métadonnées pour SHAP.

Les explications SHAP ne sont pas calculées ici (`shap.computed = false`). Ne recharger que des fichiers Joblib de confiance.

## 7. Nettoyage par playbook — Ikbel

Dans **Nettoyer mes données**, choisir les règles puis cliquer sur **Lancer le nettoyage**.

| Choix | Règles |
|---|---|
| Version 1.0 | Retrait des espaces, traitement des textes vides, conservation des lignes et des types. |
| Version 2.0 | Nettoyage des textes, conversions prévues des nombres et dates, déduplication dans les tables autorisées et contrôles des champs critiques. |
| Laisser l’assistant préparer les règles | Nouvelle proposition adaptée aux fichiers par Llama3 local. |

Les deux versions de test sont `cleaning/playbooks/playbook_v1.0.json` et `cleaning/playbooks/playbook_v2.0.json`, au format `contracts.quality.Playbook`. Elles ciblent la structure Olist. Une version sans approbation doit être validée dans l’interface avant application. Si le fichier choisi manque ou est incompatible, l’assistant propose des règles adaptées.

Dans Streamlit, ne rien sélectionner demande une génération même si une ancienne version compatible existe. Pour les commandes sans choix explicite, le moteur recherche la dernière version compatible ; un conflit de versions bloque ce choix automatique.

Pour les règles générées : lire la proposition, saisir son nom et cliquer sur **Valider et appliquer ces règles**. L’approbation est liée à l’empreinte exacte du contenu. Une modification impose une nouvelle validation. Aucun code libre produit par le modèle n’est exécuté.

Consulter ensuite les changements **avant/après**, les aperçus et le téléchargement CSV. Les montants, dates et identifiants manquants ne sont pas inventés. Les cas critiques bloquent la publication des tables nettoyées.

Sorties : `cleaning_report.json`, `tables/*.parquet`, `row_mapping.json` et, en cas de génération, proposition, approbation et playbook JSON versionné. Les propositions en attente sont liées à leur test ; les versions publiées pour réutilisation par l’interface sont conservées dans `cleaning/playbooks/`. Les anciens résultats YAML restent lisibles.

## 8. ETL et entrepôt — Ahmed

Après un nettoyage réussi, cliquer sur **Préparer mes données**. L’application inspecte toutes les sources nettoyées présentes. Llama3 propose les rôles des sources, retient des liens métier parmi les correspondances vérifiées, puis choisit un schéma parmi les organisations constructibles.

Lire le schéma, les faits, dimensions, références et la justification. Cocher **Je valide cette organisation**, puis cliquer sur **Valider et préparer**.

Les organisations possibles sont étoile, flocon, constellation, faits sans dimensions fiables ou relationnel si aucun fait n’est confirmé. Le choix est une recommandation structurelle, sans garantie d’optimalité ni benchmark de performances.

Le constructeur conserve le grain des faits, vérifie les références et compare les colonnes originales avant/après. Il ne joint pas directement plusieurs faits pour recopier leurs mesures. Les sources nettoyées restent également conservées dans le schéma `source`.

Sorties :

- `etl/warehouse.duckdb` : entrepôt, dimensions, références et copies séparées des sources nettoyées.
- `etl/warehouse_manifest.json` : schéma, justification, rôles, grains, mesures, correspondances et contrôles.
- `etl/receipts.json` : transformations, sources, jointures et nombres de lignes.
- `etl/warehouse_proposal.json` : proposition à valider, liée aux empreintes des sources.

Le nombre de tables dépend du dataset et du schéma. Un calendrier, des dimensions générées, des copies par étoile et des copies de sources peuvent augmenter ce nombre. L’interface distingue les faits et dimensions.

Le mode actuel `dimensional` n’est pas limité aux neuf noms de tables du projet. Les structures ambiguës, les clés portant des noms différents et les règles métier particulières peuvent demander un mapping supplémentaire. Les rapprochements automatiques utilisent des identifiants de mêmes noms et des chemins vérifiés limités à quatre liens. Une nouvelle structure exige une revue du plan proposé.

## 9. Graphe de lignage — Ahmed

Après l’ETL, dans **Comprendre l’origine de mes résultats** :

1. Cliquer sur **Afficher la traçabilité**.
2. Sélectionner un ensemble de données et une information.
3. Consulter le parcours source → protection → nettoyage → transformations → entrepôt.
4. Utiliser **Vérifier les sources enregistrées** pour comparer le parcours aux ancêtres enregistrés dans Neo4j.
5. Télécharger l’archive de traçabilité.

Sorties : `lineage.json`, `neo4j_import.json` et `agent_result.json`, dans `lineage/` à côté de l’ETL sélectionné. Si un ancien format doit être conservé, la nouvelle version utilise `lineage_v2_1/`.

Le graphe contient les noms et dépendances des fichiers et colonnes, sans valeurs de cellules. Chaque version est isolée ; réimporter le même graphe ne crée pas de doublons. Si Neo4j est indisponible, la copie JSON reste disponible et l’import peut être repris.

Le parcours BO2 s’arrête actuellement à l’entrepôt. L’API accepte des dépendances KPI fournies par les autres groupes, mais ne les invente pas et ne calcule pas leurs formules. `catalog_validated` reste faux : vérifier l’existence d’une colonne ne valide pas le sens métier d’un KPI.

## 10. Emplacement des résultats

Chaque import possède un dossier `runs/<identifiant>/`. Les premiers résultats sont dans `pii/`, `profiling/`, `cleaning/` et `etl/`. Les essais supplémentaires utilisent aussi `profiling_tests/`, `cleaning_tests/` et `etl_tests/`, sans remplacer les précédents.

`cleaning_current_test.json` et `etl_current_test.json` indiquent les sélections actives. L’ETL utilise le nettoyage sélectionné ; le lignage utilise l’ETL sélectionné. Le dernier résultat ne se trouve donc pas nécessairement dans le dossier initial.

Les tables intermédiaires utilisent Parquet ; les téléchargements de protection et nettoyage proposent des CSV. Le fichier `convertir_parquet_csv.py` reste disponible pour les conversions séparées. Les rapports échangés sont en JSON au format des contrats 1.1. Le journal partagé est maintenant `runs/audit_journal.db` : SQLite, ajout seul et chaîne de hash. Les anciens journaux JSONL sont conservés comme historique et ne sont plus alimentés par les agents.

Les détails propres à BO2 (schéma choisi, contrôles supplémentaires, préparation SHAP et affichage) sont séparés dans des fichiers `*.bo2.json`. Ils ne remplacent pas les fichiers échangés avec l’équipe. Une empreinte `*.bo2.sha256` lie les détails d’affichage au fichier partagé correspondant.

## 11. Tester les tâches par commande

L’interface est recommandée pour choisir les colonnes et valider. Les commandes suivantes utilisent un nouvel identifiant et les réglages initiaux du projet. Remplacer `DOSSIER_DES_FICHIERS` par son dossier.

```powershell
.\.venv\Scripts\python.exe -m bo2 step pii --dataset "DOSSIER_DES_FICHIERS" --run-id mon_test_bo2_001
.\.venv\Scripts\python.exe -m bo2 step profiling --run-id mon_test_bo2_001 --profiling-task coverage
.\.venv\Scripts\python.exe -m bo2 step profiling --run-id mon_test_bo2_001 --profiling-task anomalies
.\.venv\Scripts\python.exe -m bo2 step cleaning --run-id mon_test_bo2_001
```

Pour choisir explicitement une version, ajouter `--playbook cleaning\playbooks\playbook_v1.0.json` à la première commande de nettoyage. Si des règles ont été proposées, les lire puis les approuver et reprendre :

Si le résultat désigne plutôt un playbook partagé existant non approuvé (`outputs.playbook`), lire ce fichier puis utiliser la commande suivante pour approuver la version choisie. Remplacer `Votre nom` après revue réelle ; cette commande matérialise une décision humaine.

```powershell
.\.venv\Scripts\python.exe -m bo2 approve --proposal cleaning/playbooks/playbook_v2.0.json --reviewer "Votre nom" --output cleaning/playbooks/playbook_v2.0.json
.\.venv\Scripts\python.exe -m bo2 step cleaning --run-id mon_test_bo2_001 --playbook cleaning/playbooks/playbook_v2.0.json
```

Pour une nouvelle proposition LLM, la validation reste liée à son empreinte et suit les commandes ci-dessous :

```powershell
.\.venv\Scripts\python.exe -m bo2 approve --proposal runs/mon_test_bo2_001/cleaning/proposed_rules.json --reviewer "Votre nom" --output runs/mon_test_bo2_001/cleaning/approval.json
.\.venv\Scripts\python.exe -m bo2 step cleaning --run-id mon_test_bo2_001 --proposal runs/mon_test_bo2_001/cleaning/proposed_rules.json --approval runs/mon_test_bo2_001/cleaning/approval.json
```

Préparer ensuite l’entrepôt :

```powershell
.\.venv\Scripts\python.exe -m bo2 step etl --run-id mon_test_bo2_001 --warehouse-mode dimensional
```

Après lecture et validation de la proposition créée par cette commande :

```powershell
$etlDigest = (Get-FileHash "runs\mon_test_bo2_001\etl\warehouse_proposal.json" -Algorithm SHA256).Hash.ToLower()
.\.venv\Scripts\python.exe -m bo2 step etl --run-id mon_test_bo2_001 --warehouse-mode dimensional --etl-approval $etlDigest
.\.venv\Scripts\python.exe -m bo2 step lineage --run-id mon_test_bo2_001 --lineage-backend neo4j
```

Ces chemins de proposition correspondent au scénario CLI ci-dessus. Dans Streamlit, les nouveaux essais ont leurs propres sous-dossiers.

Le statut `needs_review` indique une vérification attendue, sans publication des tables. Le code de sortie 2 correspond à ce statut ou à `failed` : lire le résultat pour les distinguer. Un traitement terminé n’est pas écrasé. Pour une autre structure, utiliser les sélections de Streamlit ou les paramètres de l’agent afin d’adapter le profilage.

## 12. Vérifications et contrats

Depuis le projet, avec un nouveau dossier temporaire :

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=test-work/verification_bo2_001
```

Les tests couvrent protection, relations, versions, approbations, avant/après, totaux, scores, ETL, conservation des sources et lignage. Ils simulent les services ; un test réel avec Ollama et Neo4j démarrés reste distinct.

Les agents reçoivent le `RunContext` de `contracts.agent` et retournent l’`AgentResult` officiel. Les points d’entrée sont ceux de `contracts.pipeline`. Les reçus utilisent `contracts.warehouse.TransformationReceipts` et les sorties partagées sont validées par `contracts.registry.read_output`. L’ancien `contracts/artifacts.py` est retiré, conformément à la version 1.1 récupérée de `main`.

Le manifeste contient une liste de tables avec `kind` (`fact` ou `dimension`), `date_column` et les bornes de dates lorsqu’elles existent. Les références auxiliaires sont des dimensions ; les sources de rôle non confirmé restent dans DuckDB et les détails BO2, sans être présentées comme faits ou dimensions dans le manifeste partagé.

Pour vérifier la conformité :

```powershell
.\.venv\Scripts\python.exe -m contracts.check_contracts
.\.venv\Scripts\python.exe -m pytest tests/test_contract_alignment.py -q --basetemp=test-work/verification_contracts_001
```

Un contexte d’intégration se construit avec `contracts.context_for(...)`. Le journal transmis dans `ctx.journal` est utilisé par tous les agents BO2. Les anciens résultats ne sont pas réécrits : refaire un test pour obtenir les nouveaux formats. Cette conformité des échanges ne constitue pas une intégration complète des agents KPI, analyse ou dashboard.

## 13. Problèmes courants

| Situation | Action |
|---|---|
| Protection ou génération lente | Vérifier Ollama et `llama3:latest` ; une génération locale peut prendre plusieurs minutes. |
| Proposition en attente | Lire et valider les règles ou l’organisation avant de poursuivre. |
| Nettoyage bloqué | Vérifier les champs critiques et le bilan ; ne pas inventer les informations manquantes. |
| Lignage non enregistré | Démarrer Docker Desktop et Neo4j puis réessayer l’enregistrement. |
| Ancien résultat visible | Vérifier le test sélectionné ou lancer un nouvel essai. |
| Port 8501 occupé | Arrêter l’ancien serveur avec `Ctrl+C`, puis relancer `streamlit_BO2.py`. |

## Documentation complémentaire

- [Protection générique](README_PII_GENERIC.md)
- [Nettoyage](README_CLEANING.md)
- [Profilage et anomalies](README_PROFILING.md)
- [Entrepôt dimensionnel](README_ETL.md)
- [Lignage](README_LINEAGE.md)

Ce guide décrit le parcours BO2 actuel. Des guides historiques conservent des résultats d’anciennes exécutions : leurs nombres de tables ne sont pas des constantes du pipeline.
