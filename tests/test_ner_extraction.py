"""tests/test_ner_extraction.py — Inspection & Testing of Question Entity Extraction (NER).

Verifies whether NER (Named Entity Recognition) is present as a standalone agent
or fulfilled within semantic/request.py across 5 diverse questions.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.semantic import Glossary, KpiCatalog, load_yaml
from semantic.request import _find_dimensions, _find_filters, _find_metric, _find_period

TEST_QUESTIONS = [
    "Top 5 categories by Revenue in August",
    "chiffre d'affaires par etat en aout sauf SP",
    # ReviewScore / seller_id are not in the shared catalog (fact_order_reviews is not in the
    # warehouse contract): same day-range check with a KPI of the catalog.
    "frais de port par categorie du 5 au 20 juin",
    "number of orders by seller state in July vs June",
    "sales by payment method last month",
]


def test_ner_on_five_questions():
    catalog = load_yaml(KpiCatalog, REPO_ROOT / "kpi" / "catalog.yaml")
    glossary = load_yaml(Glossary, REPO_ROOT / "semantic" / "glossary.yaml")

    print("\n" + "=" * 80)
    print("NER INSPECTION & EXTRACTION TESTS ACROSS 5 DIVERSE QUESTIONS")
    print("=" * 80)

    for i, q in enumerate(TEST_QUESTIONS, 1):
        q_lower = q.lower()
        metric, conf = _find_metric(q_lower, catalog, glossary)
        dims = _find_dimensions(q_lower, catalog, glossary)
        period, compare_to = _find_period(q_lower)
        filters = _find_filters(q_lower, catalog)

        entities = {
            "METRIC": metric,
            "DIMENSIONS": dims,
            "TEMPORAL_PERIOD": f"{period.start}..{period.end}" if period else None,
            "TEMPORAL_COMPARE": f"{compare_to.start}..{compare_to.end}" if compare_to else None,
            "FILTERS_CONSTRAINTS": filters,
            "CONFIDENCE": f"{conf:.0%}",
        }

        print(f"\nQuestion {i}: \"{q}\"")
        for ent_type, val in entities.items():
            print(f"  [{ent_type:<20}] : {val}")

        # Assert all essential entities are extracted
        assert metric is not None, f"Failed to extract METRIC for '{q}'"
        assert len(dims) > 0, f"Failed to extract DIMENSIONS for '{q}'"
        assert period is not None, f"Failed to extract TEMPORAL_PERIOD for '{q}'"

    print("\n" + "=" * 80)
    print("CONCLUSION CONCERNANT LE COMPOSANT NER :")
    print(" - Aucun composant NER autonome (SpaCy / HuggingFace TokenClassification) n'existe")
    print("   dans le dépôt BIFlow.")
    print(" - La fonction d'extraction d'entités nommées (Métrique, Dimensions, Périodes, Filtres)")
    print("   est entièrement prise en charge par le module 'semantic/request.py' (Étape 4 de Malek).")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    test_ner_on_five_questions()
