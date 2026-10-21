"""test_request_synonyms.py -- Non-regression tests for BO4-06 synonym resolution.

JSON-expected results defined BEFORE execution (second-pass audit 2026-10-21).
Tests:
  - Business synonym resolution (sales -> Revenue, etc.)
  - French month names in _find_period
  - Word-boundary safety (CA must not match inside 'categorie')
  - Backward compatibility: existing EN behaviour unchanged
"""
from __future__ import annotations

import sys
import yaml
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.semantic import Glossary, KpiCatalog
from semantic.request import _find_dimensions, _find_metric, _find_period


@pytest.fixture(scope="module")
def catalog() -> KpiCatalog:
    path = REPO_ROOT / "kpi" / "catalog.yaml"
    return KpiCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def glossary() -> Glossary:
    path = REPO_ROOT / "semantic" / "glossary.yaml"
    return Glossary.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Synonym resolution -- expected JSON defined before execution
# ---------------------------------------------------------------------------

class TestSynonymResolution:
    """T-SYN-01..10 -- Business synonym + French support."""

    def test_sales_resolves_to_revenue(self, catalog, glossary):
        """T-SYN-01 -- 'sales' -> Revenue, confidence 0.75.
        Expected JSON: {"metric": "Revenue", "confidence": 0.75}
        """
        m, c = _find_metric("sales by state in august", catalog, glossary)
        assert m == "Revenue", f"Expected 'Revenue', got {m!r}"
        assert abs(c - 0.75) < 0.01

    def test_chiffre_affaires_apostrophe_droite(self, catalog, glossary):
        """T-SYN-02 -- straight apostrophe 'chiffre d'affaires' -> Revenue.
        Expected JSON: {"metric": "Revenue", "confidence": 0.75}
        """
        m, c = _find_metric("chiffre d'affaires par etat en aout", catalog, glossary)
        assert m == "Revenue"
        assert abs(c - 0.75) < 0.01

    def test_chiffre_affaires_apostrophe_bouclée(self, catalog, glossary):
        """T-SYN-03 -- curly apostrophe U+2019 'chiffre d\u2019affaires' -> Revenue.
        Expected JSON: {"metric": "Revenue", "confidence": 0.75}
        """
        m, c = _find_metric("chiffre d\u2019affaires par etat en aout", catalog, glossary)
        assert m == "Revenue"
        assert abs(c - 0.75) < 0.01

    def test_ventes_resolves_to_revenue(self, catalog, glossary):
        """T-SYN-04 -- 'ventes' -> Revenue.
        Expected JSON: {"metric": "Revenue", "confidence": 0.75}
        """
        m, c = _find_metric("ventes en aout", catalog, glossary)
        assert m == "Revenue"
        assert abs(c - 0.75) < 0.01

    def test_commandes_resolves_to_orders(self, catalog, glossary):
        """T-SYN-05 -- 'commandes' -> Orders (NOT Revenue despite 'CA' in 'categorie').
        Expected JSON: {"metric": "Orders", "confidence": 0.75}
        """
        m, c = _find_metric("commandes par categorie en septembre", catalog, glossary)
        assert m == "Orders", f"Expected 'Orders', got {m!r} (word-boundary regression)"
        assert abs(c - 0.75) < 0.01

    def test_nombre_de_commandes_resolves_to_orders(self, catalog, glossary):
        """T-SYN-06 -- 'nombre de commandes' -> Orders.
        Expected JSON: {"metric": "Orders", "confidence": 0.75}
        """
        m, c = _find_metric("nombre de commandes en juillet", catalog, glossary)
        assert m == "Orders"
        assert abs(c - 0.75) < 0.01

    def test_ca_abbreviation_resolves_to_revenue(self, catalog, glossary):
        """T-SYN-07 -- 'CA' abbreviation -> Revenue (word boundary safe).
        Expected JSON: {"metric": "Revenue", "confidence": 0.75}
        """
        m, c = _find_metric("ca en aout", catalog, glossary)
        assert m == "Revenue"

    def test_unknown_question_returns_none(self, catalog, glossary):
        """T-SYN-08 -- unrecognised question -> (None, 0.0).
        Expected JSON: {"metric": null, "confidence": 0.0}
        """
        m, c = _find_metric("what is the weather", catalog, glossary)
        assert m is None
        assert c == 0.0

    # ---------------------------------------------------------------------------
    # Backward compatibility
    # ---------------------------------------------------------------------------

    def test_direct_kpi_name_revenue_still_works(self, catalog, glossary):
        """T-SYN-09 -- backward compat: 'revenue' -> Revenue at 0.90.
        Expected JSON: {"metric": "Revenue", "confidence": 0.90}
        """
        m, c = _find_metric("revenue by state in august", catalog, glossary)
        assert m == "Revenue"
        assert abs(c - 0.90) < 0.01

    def test_direct_kpi_name_orders_still_works(self, catalog, glossary):
        """T-SYN-10 -- backward compat: 'orders' -> Orders at 0.90.
        Expected JSON: {"metric": "Orders", "confidence": 0.90}
        """
        m, c = _find_metric("orders by category in september", catalog, glossary)
        assert m == "Orders"
        assert abs(c - 0.90) < 0.01


# ---------------------------------------------------------------------------
# French month names
# ---------------------------------------------------------------------------

class TestFrenchMonths:
    """T-FM-01..06 -- French month support in _find_period."""

    def test_aout_recognised(self):
        """T-FM-01 -- 'aout' -> month 08."""
        p, _ = _find_period("revenus en aout 2017")
        assert p is not None
        assert p.start == "2017-08-01"
        assert p.end   == "2017-08-31"

    def test_janvier_recognised(self):
        """T-FM-02 -- 'janvier' -> month 01."""
        p, _ = _find_period("chiffre d'affaires en janvier")
        assert p is not None
        assert p.start[5:7] == "01"

    def test_decembre_recognised(self):
        """T-FM-03 -- 'decembre' -> month 12."""
        p, _ = _find_period("affaires en decembre 2017")
        assert p is not None
        assert p.start == "2017-12-01"
        assert p.end   == "2017-12-31"

    def test_septembre_recognised(self):
        """T-FM-04 -- 'septembre' -> month 09."""
        p, _ = _find_period("commandes en septembre")
        assert p is not None
        assert p.start[5:7] == "09"

    def test_juillet_recognised(self):
        """T-FM-05 -- 'juillet' -> month 07."""
        p, _ = _find_period("ventes en juillet")
        assert p is not None
        assert p.start[5:7] == "07"

    def test_fr_comparison_aout_vs_juillet(self):
        """T-FM-06 -- 'aout vs juillet' -> period=Aug, compare=Jul."""
        p, cmp = _find_period("revenus en aout vs juillet")
        assert p is not None and p.start[5:7] == "08"
        assert cmp is not None and cmp.start[5:7] == "07"


# ---------------------------------------------------------------------------
# Word-boundary safety
# ---------------------------------------------------------------------------

class TestWordBoundary:
    """T-WB-01..02 -- 'CA' must not match inside 'categorie'."""

    def test_ca_does_not_match_inside_categorie(self, catalog, glossary):
        """T-WB-01 -- 'categorie' alone must not trigger Revenue match."""
        m, _ = _find_metric("categorie de produits en aout", catalog, glossary)
        # No metric synonym should match -- categorie is a dimension word, not a metric
        # 'ca' is inside 'categorie' but word-boundary check must prevent false match
        # Unless the question also contains a real metric synonym
        assert m is None, (
            f"Word-boundary regression: 'categorie' triggered metric={m!r}"
        )

    def test_commandes_in_categorie_context(self, catalog, glossary):
        """T-WB-02 -- 'commandes par categorie' -> Orders, not Revenue via CA."""
        m, _ = _find_metric("commandes par categorie en aout", catalog, glossary)
        assert m == "Orders", (
            f"Word-boundary regression: got {m!r} instead of 'Orders'"
        )
