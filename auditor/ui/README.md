# Interface de l'Auditor et de BO4-12 (Tasnim)

BIFlow est un **pipeline** : Sarra dépose un fichier, pose une question, et reçoit **un seul écran de résultat**. Ma partie n'est donc pas une suite de pages à part : ce sont des **blocs** qui s'affichent dans cet écran, au bon moment.

## 1. Les blocs à placer dans l'écran de résultat (`components.py`)

| Bloc | Où le mettre | Ce qu'il fait |
|---|---|---|
| `trust_badge(run_id, journal)` | En haut, sous la question | Indique si le résultat est fiable : journal intact, état de la comparaison, drift, anomalies expliquées |
| `comparison_banner(run_id, journal)` | **Avant** les graphiques | Bandeau BO4-12 : avertissement, corrections proposées, boutons de choix. **Il renvoie les périodes que le dashboard doit utiliser**, ou `None` tant que l'utilisateur n'a pas choisi. |
| `audit_panel(run_id, journal)` | Après les graphiques (dans un menu dépliable) | Décisions de chaque agent, anomalies expliquées, intégrité, drift |
| `why_box(run_id, journal, suggestions)` | En bas | L'agent « pourquoi ? » : réponse vérifiée et preuves citées |

### Exemple d'intégration dans l'écran de résultat de Samar

```python
from auditor.ui.components import audit_panel, comparison_banner, trust_badge, why_box

trust_badge(run_id, journal)
periods = comparison_banner(run_id, journal)      # BO4-12 : (période, période comparée) ou None
if periods is None:
    st.info("Le dashboard sera affiché après votre choix.")
else:
    draw_dashboard(run_id, *periods)              # ← les graphiques de Samar
with st.expander("Audit de ce run"):
    audit_panel(run_id, journal)
why_box(run_id, journal, ["Pourquoi ce chiffre ?"])
```

La page **« Résultat d'un run »** (`run_view.py`) montre exactement cet assemblage. Le graphique du milieu y est **provisoire** : c'est la place du dashboard de Samar.

## 2. Les pages détaillées (pour explorer et pour la démo)

Ces pages ne remplacent pas l'écran de résultat. Elles servent à **aller plus loin** sur un sujet, et à la démo devant le prof.

| Page | Ce qu'elle montre |
|---|---|
| Comparaisons (BO4-12) | Les 5 contrôles en détail, le graphique de couverture, et l'agent lancé sur **une comparaison de ton choix** |
| Expliquer une anomalie | SHAP, ligne par ligne |
| Demander pourquoi ? | L'agent sur n'importe quel run de n'importe quel journal |
| Journal d'audit | Toutes les entrées, la vérification, et la démonstration de falsification (sur une copie) |
| Drift | Le diagnostic par mois, les cartes de contrôle et le PSI |

## 3. Lancer et tester

Depuis la racine du projet, avec le `.venv` activé :

```
pip install streamlit matplotlib
streamlit run auditor/ui/app.py
```

**Tests automatiques.** Ils ouvrent chaque page et chaque bloc sans navigateur, et vérifient qu'il n'y a aucune erreur :

```
python -m pytest tests/test_ui.py -v
```

**Données de démo.** Ces commandes se lancent une seule fois, avant les tests :

```
python -m contracts.examples.install
python -m auditor.dev.make_fake_inputs
python -m auditor.dev.seed_demo_journal
python -m auditor.dev.simulate_runs
python -m auditor.drift.monitor
```
