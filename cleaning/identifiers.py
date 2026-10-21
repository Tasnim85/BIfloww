"""Recognise identifiers, amounts and dates from the words of a column name, in any language.

'order_id', 'id_client', 'num_commande', 'CustomerID', 'Nº_facture' and 'payment_sequential'
are identifiers: cleaning never casts, fills or corrects them. Before, only names ending in
'_id' or '_key' were recognised.

The cleaning agent keeps its own copy of these words (README rule 4: an agent never imports
another agent's code); they are the same words as etl/generic.py.
"""
import re
import unicodedata

KEY_WORDS = {"id", "ids", "identifier", "identifiant", "key", "code", "ref", "reference", "uuid", "guid",
             "num", "no", "nr", "numero", "nummer", "cle"}
SEQUENCE_WORDS = {"sequential", "sequence", "seq"}           # line number inside an order
COORDINATE_WORDS = {"lat", "lng", "lon", "latitude", "longitude"}
FINANCIAL_TERMS = ("price", "amount", "value", "freight", "payment")      # English, inside a name
FINANCIAL_WORDS = {"montant", "prix", "valeur", "frais", "paiement", "cout", "tarif"}
TEMPORAL_TERMS = ("date", "time")
TEMPORAL_WORDS = {"heure", "horodatage"}


def name_words(column):
    """'order_purchase_timestamp' -> ['order', 'purchase', 'timestamp']; 'CustomerID' -> ['customer', 'id']."""
    plain = unicodedata.normalize("NFKD", column).encode("ascii", "ignore").decode()
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", plain)
    return [w for w in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if w]


def is_identifier(column):
    return bool((KEY_WORDS | SEQUENCE_WORDS) & set(name_words(column)))


def is_coordinate(column):
    return bool(COORDINATE_WORDS & set(name_words(column)))


def is_financial(column):
    return any(term in column.lower() for term in FINANCIAL_TERMS) or bool(FINANCIAL_WORDS & set(name_words(column)))


def is_temporal(column):
    lower = column.lower()
    return (any(term in lower for term in TEMPORAL_TERMS) or lower.endswith("_at")
            or bool(TEMPORAL_WORDS & set(name_words(column))))
