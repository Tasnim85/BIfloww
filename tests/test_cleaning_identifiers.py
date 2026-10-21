"""Cleaning recognises identifiers in any language, not only names ending in _id or _key."""
import json
from pathlib import Path

import pandas as pd
import pytest

from cleaning.book_contract import from_local
from cleaning.identifiers import is_financial, is_identifier
from cleaning.llm_rules import Rule
from cleaning.shared_playbook import run as run_playbook
from contracts.agent import RunContext
from contracts.quality import CleaningRule, Playbook

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAYBOOKS = REPO_ROOT / "cleaning" / "playbooks"


@pytest.mark.parametrize("column", ["order_id", "customer_unique_id", "id_client", "num_commande",
                                    "CustomerID", "Nº_facture", "code_produit", "ref_article",
                                    "payment_sequential", "numero_rdv", "product_key"])
def test_identifiers(column):
    assert is_identifier(column)


@pytest.mark.parametrize("column", ["price", "payment_value", "product_weight_g", "customer_city",
                                    "payment_installments", "montant", "statut", "date_rdv",
                                    "product_name_lenght", "video"])
def test_not_identifiers(column):
    assert not is_identifier(column)


def test_french_amounts_are_financial():
    assert all(is_financial(c) for c in ["montant", "prix_unitaire", "frais_livraison", "payment_value"])


@pytest.mark.parametrize("column", ["id_client", "num_commande", "CustomerID"])
def test_llm_rule_never_casts_an_identifier(column):
    with pytest.raises(ValueError, match="identifiers"):
        Rule(table="t", column=column, action="numeric")


def test_llm_rule_never_fills_a_french_amount():
    with pytest.raises(ValueError, match="fabricate"):
        Rule(table="t", column="montant", action="fill_constant", value=0)


def test_olist_playbook_is_unchanged():
    """The published Olist playbook v2.0 is rebuilt identically: nothing changes for Olist."""
    config = json.loads((PLAYBOOKS / "playbook_v2.0.bo2.json").read_text(encoding="utf-8"))
    published = Playbook.model_validate_json((PLAYBOOKS / "playbook_v2.0.json").read_text(encoding="utf-8"))
    assert from_local(config).rules == published.rules


def test_built_in_playbook_does_not_cast_french_identifiers():
    config = {"name": "clinique", "version": "1.0", "required_tables": ["rdv"],
              "actions": {"empty_strings_to_null": True, "remove_exact_duplicate_rows": False},
              "deduplicate_tables": [],
              "numeric_columns": {"rdv": ["num_rdv", "id_patient", "montant", "Nº_facture"]}}
    casts = [r.column for r in from_local(config).rules if r.action.value == "cast"]
    assert casts == ["montant"]


def test_shared_playbook_never_fills_a_french_identifier(tmp_path):
    tables = tmp_path / "pii" / "tables"
    tables.mkdir(parents=True)
    pd.DataFrame({"id_client": ["a", None], "ville": ["Tunis", "Sfax"]}).to_parquet(tables / "clients.parquet")
    book = Playbook(name="test", version="1.0", source="manual", approved_by="ikbel",
                    approved_at="2026-10-21T00:00:00Z",
                    rules=[CleaningRule(rule_id="R1", table="clients", column="id_client",
                                        action="fill_value", params={"value": "x"}, description="test")])
    ctx = RunContext(run_id="t", agent="cleaning", inputs={"tables": tables}, output_dir=tmp_path / "cleaning",
                     journal=tmp_path / "journal.db")
    with pytest.raises(ValueError, match="fabricate"):
        run_playbook(ctx, book)
