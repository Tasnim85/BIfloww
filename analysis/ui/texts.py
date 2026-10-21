"""Every text of Rabeb's pages, in English and French: t("run.title") -> the text in the
language chosen in the sidebar (st.session_state["lang"], the same key as Tasnim's app).

Step 7 will move these texts into the team catalogs i18n/en.yaml and i18n/fr.yaml once
Tasnim's i18n is in main; the keys stay the same.
"""
import streamlit as st

TEXTS = {
    "en": {
        "lang_label": "Language",
        "pages.run": "Analysis result", "pages.catalog": "KPI catalog", "pages.proposer": "KPI proposer",
        "common.run": "Run", "common.no_run": "No run with this data yet. Create the mini warehouse:",
        "common.llm": "LLM: {status}", "common.key_present": "key present", "common.key_missing": "no key",
        "kpi.value": "{kpi} · {start} → {end}", "kpi.previous": "Compared with {start} → {end}",
        "kpi.version": "KPI used", "kpi.valid": "✅ Validated (BO3-03: {n} checks passed)",
        "kpi.invalid": "⛔ Not validated: {failed}",
        "checks.title": "BO3-03 checks: does the number follow the approved definition?",
        "checks.passed": "passed", "checks.failed": "FAILED",
        "checks.name.grain_matches_kpi": "Grain of the table = grain of the KPI",
        "checks.name.join_multiplicity": "Joins did not duplicate rows",
        "checks.name.reference_value": "Breakdown adds up to the reference total",
        "checks.name.etl_receipt": "ETL receipt confirms the fact table",
        "insights.title": "What explains the result",
        "insights.llm": "🤖 Written by the LLM agent, every number checked against the facts",
        "insights.fallback": "📐 Fixed sentences (the LLM was not used)",
        "insights.none": "No insight: the checks did not pass, so nothing is explained.",
        "insights.facts": "Facts behind this sentence",
        "sql.title": "Exact SQL run on the warehouse (built from the catalog, never by an LLM)",
        "run.title": "Analysis result", "run.caption": "Step 5 (Rabeb): the KPI, its validation and its insights.",
        "run.question": "Question: {q}", "run.no_result": "This run has no analysis result yet.",
        "run.launch": "Run the Analyst on this run", "run.use_llm": "Use the LLM for the insights",
        "run.running": "The Analyst is working...", "run.done": "{status}: {message}",
        "run.chart": "{kpi} by {dim}", "run.current": "studied period", "run.prev": "compared period",
        "cat.title": "KPI catalog", "cat.caption": "The only place where a KPI formula is defined (kpi/catalog.yaml).",
        "cat.kpis": "KPIs ({n})", "cat.dims": "Dimensions ({n})", "cat.glossary": "Glossary: the manager's words",
        "cat.try": "Try a KPI on a warehouse", "cat.kpi": "KPI", "cat.dim": "Split by",
        "cat.none": "(total)", "cat.start": "From", "cat.end": "To", "cat.go": "Compute",
        "cat.result": "Result", "cat.error": "Refused: {e}",
        "prop.title": "KPI proposer", "prop.caption": "A DRAFT catalog for any dataset. A human reviews it before use.",
        "prop.data_of": "Warehouse of run", "prop.use_llm": "Let the LLM choose and name the KPIs",
        "prop.go": "Propose", "prop.running": "Reading the warehouse...",
        "prop.result": "Draft ({source}): {k} KPIs, {d} dimensions",
        "prop.approved": "Already in the approved catalog (kept as they are)", "prop.new": "New: to review",
        "prop.review": "Before copying: check names and units, add the business filters (e.g. order_status = 'delivered').",
        "prop.dl_catalog": "Download the catalog draft", "prop.dl_glossary": "Download the glossary draft",
    },
    "fr": {
        "lang_label": "Langue",
        "pages.run": "Résultat d'analyse", "pages.catalog": "Catalogue des KPI", "pages.proposer": "Proposeur de KPI",
        "common.run": "Run", "common.no_run": "Aucun run avec ces données. Crée le mini entrepôt :",
        "common.llm": "LLM : {status}", "common.key_present": "clé présente", "common.key_missing": "pas de clé",
        "kpi.value": "{kpi} · {start} → {end}", "kpi.previous": "Comparé à {start} → {end}",
        "kpi.version": "KPI utilisé", "kpi.valid": "✅ Validé (BO3-03 : {n} contrôles réussis)",
        "kpi.invalid": "⛔ Non validé : {failed}",
        "checks.title": "Contrôles BO3-03 : le chiffre suit-il la définition approuvée ?",
        "checks.passed": "réussi", "checks.failed": "ÉCHEC",
        "checks.name.grain_matches_kpi": "Granularité de la table = granularité du KPI",
        "checks.name.join_multiplicity": "Les jointures n'ont pas dupliqué de lignes",
        "checks.name.reference_value": "La ventilation retombe sur le total de référence",
        "checks.name.etl_receipt": "Le reçu de l'ETL confirme la table de faits",
        "insights.title": "Ce qui explique le résultat",
        "insights.llm": "🤖 Écrit par l'agent LLM, chaque nombre vérifié dans les faits",
        "insights.fallback": "📐 Phrases fixes (le LLM n'a pas été utilisé)",
        "insights.none": "Aucun insight : les contrôles n'ont pas réussi, donc rien n'est expliqué.",
        "insights.facts": "Faits derrière cette phrase",
        "sql.title": "SQL exact exécuté sur l'entrepôt (construit depuis le catalogue, jamais par un LLM)",
        "run.title": "Résultat d'analyse", "run.caption": "Étape 5 (Rabeb) : le KPI, sa validation et ses insights.",
        "run.question": "Question : {q}", "run.no_result": "Ce run n'a pas encore de résultat d'analyse.",
        "run.launch": "Lancer l'Analyst sur ce run", "run.use_llm": "Utiliser le LLM pour les insights",
        "run.running": "L'Analyst travaille...", "run.done": "{status} : {message}",
        "run.chart": "{kpi} par {dim}", "run.current": "période étudiée", "run.prev": "période comparée",
        "cat.title": "Catalogue des KPI", "cat.caption": "Le seul endroit où une formule de KPI est définie (kpi/catalog.yaml).",
        "cat.kpis": "KPI ({n})", "cat.dims": "Dimensions ({n})", "cat.glossary": "Glossaire : les mots de la manager",
        "cat.try": "Essayer un KPI sur un entrepôt", "cat.kpi": "KPI", "cat.dim": "Ventilé par",
        "cat.none": "(total)", "cat.start": "Du", "cat.end": "Au", "cat.go": "Calculer",
        "cat.result": "Résultat", "cat.error": "Refusé : {e}",
        "prop.title": "Proposeur de KPI", "prop.caption": "Un BROUILLON de catalogue pour n'importe quelles données. Un humain le relit avant usage.",
        "prop.data_of": "Entrepôt du run", "prop.use_llm": "Laisser le LLM choisir et nommer les KPI",
        "prop.go": "Proposer", "prop.running": "Lecture de l'entrepôt...",
        "prop.result": "Brouillon ({source}) : {k} KPI, {d} dimensions",
        "prop.approved": "Déjà dans le catalogue approuvé (gardés tels quels)", "prop.new": "Nouveaux : à relire",
        "prop.review": "Avant de copier : vérifie les noms et les unités, ajoute les filtres métier (ex. order_status = 'delivered').",
        "prop.dl_catalog": "Télécharger le brouillon du catalogue", "prop.dl_glossary": "Télécharger le brouillon du glossaire",
    },
}
LANGS = tuple(TEXTS)


def ui_lang() -> str:
    lang = st.session_state.get("lang", "en")
    return lang if lang in TEXTS else "en"


def t(key: str, /, **params) -> str:
    text = TEXTS[ui_lang()].get(key) or TEXTS["en"].get(key, key)
    return text.format(**params) if params else text
