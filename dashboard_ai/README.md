# dashboard_ai — Étape 6 : dashboard intelligent (BO4)

Choisit **le type de graphique optimal** pour la question de Sarra et les métriques calculées,
et **détecte les représentations trompeuses**. Même « prise » que `app.dashboard:run`
(entrées `request`, `result`, `data`, `comparisons` → sortie `dashboard_spec.json`), contrat `DashboardSpec` inchangé.

| Fichier | Rôle |
|---|---|
| `rules.py` | seuils versionnés (`dashboard-rules@1.0`) : parts max d'un camembert, top N des barres, effet de base… |
| `intent.py` | ce que veut voir la question (tendance, part, classement, comparaison, détail) + graphique demandé (FR/EN) |
| `profile.py` | nature des axes, cardinalité, KPI **additif** ou non (`COUNT DISTINCT`, moyennes, ratios : non) |
| `selector.py` | score + raisons pour chaque `ChartType`, les types impossibles sont écartés avec la raison |
| `misleading.py` | pièges visuels : catégorie dominante, écarts négligeables, trou dans l'axe du temps, effet de base, unités mélangées |
| `prepare.py` | données prêtes à tracer : tri, top N (+ « Autres » si additif), alignement de deux périodes par position |
| `agent.py` | `run(ctx)` pour l'orchestrateur, `build_dashboard(...)` fonction pure |
| `render.py` | rendu matplotlib (lab / notebook) : barres à zéro, pas d'axe double |
| `lab/lab_dashboard.py` | lab exécutable, 9 scénarios |
| `notebooks/06_dashboard_intelligent.ipynb` | notebook exécuté (figures intégrées) |
| `integration.patch` | 3 modifications optionnelles dans des fichiers de l'équipe (voir plus bas) |

## Règles de décision

1. **Éligibilité** (peut-on dire la vérité avec ces données ?) : camembert → 1 dimension catégorielle, 2 à 6 parts, KPI additif,
   pas de négatifs, une seule période ; courbe → axe temporel d'au moins 3 points ; carte → désactivée tant que l'app n'a pas de rendu.
2. **Préférence** (que veut voir la question ?) : tendance → courbe, part → camembert, classement/comparaison → barres, 3+ dimensions ou détail → tableau.
3. **Demande explicite** (« en camembert ») : respectée si éligible, sinon **refusée avec la raison** et remplacée.
4. **Comparaison** : si `comparisons/` a un contrôle `BLOCKING` et que Sarra n'a pas rejeté la correction, la période précédente n'est **pas tracée**.
   `accepted` → chiffres ajustés dans l'en-tête ; `rejected` → tracée telle que demandée avec l'alerte.
5. **Données incomplètes** (`value` ou une dimension absente de `result.parquet`) : mode dégradé, carte KPI seule + alerte.

## Utilisation

```bash
python -m dashboard_ai.lab.lab_dashboard --lang fr          # 9 scénarios, PNG + summary.csv dans dashboard_ai/lab/out
python -m dashboard_ai.lab.lab_dashboard --only pie_27
jupyter notebook dashboard_ai/notebooks/06_dashboard_intelligent.ipynb
python -m pytest tests/test_dashboard_ai.py -v
```

Paramètres de `RunContext.params` : `lang` (`"en"` par défaut, `"fr"`), `rules` (surcharge des seuils, ex. `{"pie_max_slices": 5}`).

## Sorties

* `dashboard_spec.json` — contrat existant ; `ChartSpec.reason` explique le choix, `warnings` contient les alertes.
* `chart_advice.json` — fichier annexe pour l'Auditor : classement de **tous** les types avec scores et raisons, alertes typées.
* `c_kpi.parquet`, `c_main.parquet` — données préparées, colonne `y` toujours `value`.
* Journal d'audit : un événement `chart_selected` et un `visual_issue` par alerte, avec `rule_version`.

## Intégration (optionnelle, `git apply dashboard_ai/integration.patch`)

1. `contracts/pipeline.py` : `entrypoint="dashboard_ai.agent:run"` (le contrat ne change pas).
2. `app/app.py` : rendu du type `pie` (absent jusqu'ici) et courbes avec `color` (deux périodes superposées).
3. `tests/test_pipeline_e2e.py` : le stub d'analyse écrivait une colonne `Revenue` ; le vrai Analyst écrit `<dimensions>, period, value`
   (voir `analysis/sql_compiler.py`). Sans cette correction, ce test obtient 1 graphique + alerte au lieu de 2.

> `app/dashboard.py` utilisait `y=request.metric.lower()` (« revenue »), colonne qui n'existe pas dans `result.parquet` :
> l'app retombait sur un tableau. Ici `y` vaut toujours `value`.

## Limites connues

* Le rendu Streamlit du `pie` n'a pas pu être exécuté dans l'environnement de développement (pas d'interface) ; seule la syntaxe est vérifiée.
* La carte (`map`) est désactivée (`Rules.map_enabled=False`) tant que l'app n'a pas de rendu cartographique.
* Les mots-clés d'intention couvrent FR/EN ; une autre langue retombe sur le choix par la forme des données.
* Les ajustements acceptés par Sarra (`same_days`…) modifient l'en-tête, pas le détail par dimension : celui-ci demanderait de relancer l'Analyst sur la fenêtre ajustée.
