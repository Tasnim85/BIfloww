# Interface de l'Analyst (Rabeb)

Même organisation que la partie de Tasnim (`auditor/ui/`) : des **blocs** à placer dans l'écran de résultat de Samar, et des **pages** pour explorer et pour la démo.

## 1. Les blocs pour l'écran de résultat (`components.py`)

| Bloc | Où le mettre | Ce qu'il fait |
|---|---|---|
| `kpi_header(run_id)` | En haut, sous la question | Le chiffre, la comparaison, la version du KPI (`Revenue@2.0`), et « validé » ou non |
| `insights_box(run_id)` | Sous les graphiques | Ce qui explique le résultat, avec les faits derrière chaque phrase |
| `validation_panel(run_id)` | Dans « Audit de ce run » | Les 4 contrôles BO3-03 avec leurs chiffres |
| `sql_box(run_id)` | Dans « Audit de ce run » | Le SQL exact, construit depuis le catalogue |

```python
from analysis.ui.components import insights_box, kpi_header, sql_box, validation_panel

kpi_header(run_id)
draw_dashboard(run_id)            # ← les graphiques de Samar
insights_box(run_id)
with st.expander("Audit de ce run"):
    validation_panel(run_id)
    sql_box(run_id)
```

## 2. Les pages

| Page | Ce qu'elle montre |
|---|---|
| Résultat d'analyse | Un run complet avec tous les blocs, et un bouton pour relancer l'Analyst (avec ou sans LLM) |
| Catalogue des KPI | Les KPI, les dimensions et le glossaire, et un KPI calculé en direct sur un entrepôt, avec ses contrôles |
| Proposeur de KPI | Le brouillon de catalogue pour l'entrepôt d'un run, à télécharger et à relire |

## 3. Lancer et tester

Depuis la racine du projet :

```
pip install streamlit matplotlib
python -m analysis.dev_warehouse
python -m analysis.analyst dev_001
streamlit run analysis/ui/app.py
```

Tests automatiques, sans navigateur. Ils travaillent dans un dossier temporaire et ne touchent pas à `runs/` :

```
python -m pytest tests/test_analysis_ui.py -v
```

Les textes sont dans `texts.py` (anglais et français). À l'étape 7, ils iront dans les catalogues `i18n/` de l'équipe, avec les mêmes clés.
