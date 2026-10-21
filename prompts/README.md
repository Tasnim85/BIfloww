# BIFlow : les prompts

Tous les prompts LLM du projet sont rangés **ici**, un fichier YAML par prompt. Aucun prompt n'est écrit dans le code Python : le code charge le fichier avec `load_prompt("<nom>")`.

## Modifier un prompt

1. Modifie le texte dans `system:`.
2. Augmente `version`, par exemple de `"1.2"` à `"1.3"`.
3. Ajoute **en haut** de `changelog` une entrée qui donne la nouvelle version, la date, ton nom, et ce que tu as changé et pourquoi.
4. Lance `python -m contracts.check_contracts`. Il refuse un prompt dont la version ne correspond pas à la première entrée du changelog.

Tu n'as rien à changer dans le code : le fichier est relu à chaque appel.

## Les variables

Une variable s'écrit `$language` dans le texte, et non `{language}`, pour que les accolades d'un exemple JSON ne posent pas de problème. Chaque variable doit être déclarée dans `variables:`, sinon le chargement échoue.

## La traçabilité

Chaque appel au LLM est inscrit dans le journal d'audit avec :

- `rule_version` = `prompt:<nom>@<version>` ;
- l'empreinte (`prompt_sha256`) du texte exact envoyé.

On peut donc toujours retrouver quelle version du prompt a produit une réponse.

Pour lister tous les prompts du projet :

```
python -m contracts.prompts
```

## Les prompts actuels

| Fichier | Propriétaire | Utilisé par |
|---|---|---|
| `comparison_summary.yaml` | Tasnim | `comparisons/narrate.py` (BO4-12) |
| `why_agent.yaml` | Tasnim | `auditor/why.py` (BO3 : l'enquêteur de l'agent « pourquoi ? ») |
| `why_writer.yaml` | Tasnim | `auditor/why.py` (BO3 : le rédacteur de la réponse finale) |
