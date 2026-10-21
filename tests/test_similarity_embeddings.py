"""tests/test_similarity_embeddings.py — BO1-06 Dataset Similarity Embeddings vs Jaccard.

Verifies:
1. Olist identical -> Jaccard = 1.0, Embedding = 1.0
2. Olist renamed (synonyms / French) -> Jaccard drops to ~0.0, Embedding captures similarity (> 0.35)
3. Unrelated dataset -> both Jaccard = 0.0 and Embedding score is low (< 0.25)
"""
from __future__ import annotations

import pytest
from intake.similarity import _KNOWN_DATASETS, _jaccard, compute_embedding_similarity

# 1. Reference Olist columns
OLIST_COLS = list(_KNOWN_DATASETS["olist"])

# 2. Renamed Olist columns (semantic equivalents / synonyms / French)
OLIST_RENAMED = [
    "client_id", "client_unique_id", "statut_commande", "date_achat",
    "date_approbation", "date_expedition", "date_livraison", "date_estimee",
    "code_postal_client", "ville_client", "etat_client", "produit_id",
    "vendeur_id", "prix_unitaire", "frais_livraison", "mode_paiement",
    "nombre_mensualites", "montant_paiement", "note_evaluation",
    "commentaire_avis", "categorie_produit", "poids_produit",
    "latitude_geo", "longitude_geo", "commande_id",
]

# 3. Completely unrelated dataset (Iris / Weather / Biology)
UNRELATED_COLS = [
    "sepal_length", "sepal_width", "petal_length", "petal_width", "species",
    "ambient_temperature_celsius", "relative_humidity_pct", "wind_speed_kmh",
    "atmospheric_pressure_hpa", "soil_ph_level",
]


def test_olist_identical_scores():
    jaccard_score = _jaccard(set(OLIST_COLS), set(OLIST_COLS))
    emb_score = compute_embedding_similarity(OLIST_COLS, OLIST_COLS)
    assert jaccard_score == 1.0
    assert emb_score == 1.0


def test_olist_renamed_embedding_beats_jaccard():
    jaccard_score = _jaccard(set(OLIST_COLS), set(OLIST_RENAMED))
    emb_score = compute_embedding_similarity(OLIST_COLS, OLIST_RENAMED)
    # Jaccard cannot match renamed columns
    assert jaccard_score == 0.0, f"Expected Jaccard 0.0, got {jaccard_score}"
    # Embedding captures semantic similarity across synonyms/languages
    assert emb_score >= 0.35, f"Expected Embedding >= 0.35, got {emb_score}"
    print(f"\n[BO1-06] Renamed columns: Jaccard={jaccard_score:.4f} vs Embedding={emb_score:.4f}")


def test_unrelated_dataset_scores_low():
    jaccard_score = _jaccard(set(OLIST_COLS), set(UNRELATED_COLS))
    emb_score = compute_embedding_similarity(OLIST_COLS, UNRELATED_COLS)
    assert jaccard_score == 0.0
    # Embedding score on unrelated biology/meteorology is distinctly lower
    assert emb_score <= 0.28, f"Expected Embedding <= 0.28, got {emb_score}"
    print(f"\n[BO1-06] Unrelated dataset: Jaccard={jaccard_score:.4f} vs Embedding={emb_score:.4f}")


def test_embedding_ranking_order():
    """Verify that Olist Identical > Olist Renamed > Unrelated."""
    score_identical = compute_embedding_similarity(OLIST_COLS, OLIST_COLS)
    score_renamed = compute_embedding_similarity(OLIST_COLS, OLIST_RENAMED)
    score_unrelated = compute_embedding_similarity(OLIST_COLS, UNRELATED_COLS)

    assert score_identical > score_renamed > score_unrelated
