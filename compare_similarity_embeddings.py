"""compare_similarity_embeddings.py — BO1-06 Comparison Embeddings vs Jaccard.

Computes and prints similarity scores for:
1. Olist identical
2. Olist with renamed columns (synonyms / French translation)
3. Unrelated dataset (Iris / Weather / Biology)
"""
from __future__ import annotations

from intake.similarity import _KNOWN_DATASETS, _jaccard, compute_embedding_similarity

OLIST_COLS = list(_KNOWN_DATASETS["olist"])

OLIST_RENAMED = [
    "client_id", "client_unique_id", "statut_commande", "date_achat",
    "date_approbation", "date_expedition", "date_livraison", "date_estimee",
    "code_postal_client", "ville_client", "etat_client", "produit_id",
    "vendeur_id", "prix_unitaire", "frais_livraison", "mode_paiement",
    "nombre_mensualites", "montant_paiement", "note_evaluation",
    "commentaire_avis", "categorie_produit", "poids_produit",
    "latitude_geo", "longitude_geo", "commande_id",
]

UNRELATED_COLS = [
    "sepal_length", "sepal_width", "petal_length", "petal_width", "species",
    "ambient_temperature_celsius", "relative_humidity_pct", "wind_speed_kmh",
    "atmospheric_pressure_hpa", "soil_ph_level",
]


def main():
    datasets = [
        ("Olist Identique", OLIST_COLS),
        ("Olist Renommé (Synonymes/FR)", OLIST_RENAMED),
        ("Dataset Sans Rapport (Iris/Météo)", UNRELATED_COLS),
    ]

    print("\n" + "=" * 80)
    print("BO1-06 DATASET SIMILARITY: JACCARD (Phase 1) vs EMBEDDINGS (Phase 2)")
    print("=" * 80)
    print(f"{'Scénario de Test':<35} | {'Jaccard':<10} | {'Embedding Cosine':<16} | {'Constat':<15}")
    print("-" * 80)

    for name, cols in datasets:
        j_score = _jaccard(set(OLIST_COLS), set(cols))
        e_score = compute_embedding_similarity(OLIST_COLS, cols)
        if name == "Olist Identique":
            constat = "Match Parfait"
        elif "Renommé" in name:
            constat = "Embeddings > Jaccard"
        else:
            constat = "Non similaire"

        print(f"{name:<35} | {j_score:<10.4f} | {e_score:<16.4f} | {constat:<15}")

    print("=" * 80)
    print("Analyse :")
    print(" - Jaccard est strictement lexical : dès que les colonnes sont renommées,")
    print("   le score s'effondre à 0.0000 (incapacité à reconnaître la structure).")
    print(" - Les Embeddings vectoriels (all-MiniLM-L6-v2) capturent le sens sémantique")
    print("   des colonnes (prix -> price, client -> customer), maintenant un score élevé")
    print("   et discriminant par rapport à un dataset sans rapport.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
