# Textes multilingues (français / anglais)

Le système affiche ses textes en **français ou en anglais**. Le code est dans `contracts/i18n.py`, les phrases dans ce dossier.

## Le principe

Un agent n'écrit jamais directement une phrase dans une langue. Il écrit un **message** : une clé du catalogue et les valeurs brutes à insérer.

```python
from contracts.i18n import Msg, render

parts = [Msg(key="cmp.scale.ok", params={"n_cur": 31, "n_prev": 29})]
check = ComparisonCheck(..., message=render(parts), message_parts=parts)   # anglais + version multilingue
```

- `en.yaml` : `"Periods of {n_cur:int} and {n_prev:int} days: lengths are comparable."`
- `fr.yaml` : `"Périodes de {n_cur:int} et {n_prev:int} jours : les durées sont comparables."`

À l'affichage, `localize(rapport, "fr")` réécrit tous les textes dans la langue demandée. L'API le fait avec `?lang=fr|en` (ou l'en-tête `Accept-Language`), Streamlit avec le sélecteur de la barre latérale.

## L'interface Streamlit aussi

Tous les textes de l'application Streamlit (titres, boutons, badges, tableaux) sont dans la section **`ui`** des deux catalogues. Dans le code de l'interface : `t("run.title")` donne « Run result » ou « Résultat d'un run » selon le sélecteur de langue. L'application s'ouvre en **anglais** (la langue de la démo), sauf si `BIFLOW_UI_LANG=fr`. Un test vérifie qu'aucun mot français ne reste sur aucune page en mode anglais.

## Les règles

| Règle | Pourquoi |
|---|---|
| **L'anglais est la langue de référence** : les champs texte des contrats (`message`, `narrative`...) et le **journal d'audit** restent en anglais | La chaîne de hachage, les recherches de l'agent « pourquoi ? » et les tests ne dépendent pas de la langue du lecteur |
| **Les nombres sont formatés par le code**, jamais écrits dans le catalogue | `{v:num2}` donne `941,291.36` en anglais et `941 291,36` en français, et la valeur ne change jamais |
| **Pas de LLM pour traduire** | Une traduction automatique pourrait modifier un chiffre ; ici c'est impossible |
| Les textes rédigés par le LLM (résumé BO4-12, réponses « pourquoi ? ») sont **écrits directement dans la langue** demandée | La réponse « pourquoi ? » suit la langue de la question (détectée) ; un résumé LLM dans une autre langue que celle demandée est remplacé par le gabarit traduit |
| Chaque clé existe dans **les deux** fichiers, avec **les mêmes** `{placeholders}` | Vérifié par `python -m contracts.check_contracts` et `tests/test_i18n.py` |

## Formats des valeurs

| Écriture | Anglais | Français |
|---|---|---|
| `{x}` | texte tel quel (une liste est jointe par « , ») | idem |
| `{x:num2}` | 941,291.36 | 941 291,36 |
| `{x:num0}` / `{x:int}` / `{x:f1}` | 1,234 / 1234 / 3.5 | 1 234 / 1234 / 3,5 |
| `{x:auto}` | entier → `num0`, sinon `num2` | idem |
| `{x:pct}` / `{x:pct0}` / `{x:spct}` | 34.6% / 35% / +34.6% | 34,6 % / 35 % / +34,6 % |
| `{x:t}` | `x` est une clé du catalogue (ex. `word.current`) | traduite aussi |
| `{x:msg}` / `{x:msgs}` | `x` est un message (ou une liste) imbriqué | traduit aussi |

## Ajouter un texte (pour toute l'équipe)

1. Ajoute la clé dans `en.yaml` **et** dans `fr.yaml`, sous la section de ton agent.
2. Dans ton agent : `parts = [Msg(key=..., params=...)]`, puis remplis `X=render(parts)` et `X_parts=parts`.
3. Lance `python -m contracts.check_contracts`.

## Limite connue

Les **noms qui viennent des données** restent tels qu'ils sont dans les données : nom du KPI (« Revenue »), noms de colonnes (« customer state »), libellés du profiling (« Payment value »), table (« orders »). Pour les traduire aussi, le glossaire métier (`semantic/glossary.yaml`) devrait donner un libellé par langue.
