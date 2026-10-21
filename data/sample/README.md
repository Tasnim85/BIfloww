# BIFlow — Échantillon Olist pour Tests et Intégration (500 Commandes)

> [!IMPORTANT]
> **AVERTISSEMENT D'AUDIT :**
> Ces 8 fichiers CSV constituent un **échantillon synthétique de substitution**, calibré pour respecter exactement les schémas, types et contraintes relationnelles du jeu de données Olist réel.
> **Ils ne proviennent pas d'une extraction brute de données réelles Kaggle**, ce qui garantit l'absence totale de données personnelles réelles (PII) conformément aux règles du projet.

## Tables livrées (8 tables complètes)

| Fichier | Lignes | Clé primaire | Rôle / Liens |
|---------|--------|--------------|--------------|
| `olist_orders_dataset.csv` | 500 | `order_id` | Table centrale des commandes (500 commandes réparties sur 2017-2018). FK: `customer_id` |
| `olist_customers_dataset.csv` | 420 | `customer_id` | Données clients réparties sur 11 états brésiliens |
| `olist_order_items_dataset.csv` | 619 | (`order_id`, `order_item_id`) | Lignes de commande. FK: `order_id`, `product_id`, `seller_id` |
| `olist_order_payments_dataset.csv` | 500 | (`order_id`, `payment_sequential`) | Montants et modes de paiement. FK: `order_id` |
| `olist_order_reviews_dataset.csv` | 356 | `review_id` | Avis clients et scores (1 à 5). FK: `order_id` |
| `olist_products_dataset.csv` | 120 | `product_id` | Produits et catégories (10 catégories distinctes) |
| `olist_sellers_dataset.csv` | 40 | `seller_id` | Vendeurs répartis sur les états brésiliens |
| `olist_geolocation_dataset.csv` | 115 | — | Coordonnées GPS des préfixes postaux |

## Intégrité Référentielle Vérifiée

100% des clés étrangères sont vérifiées et garanties sans orphelins :
- `orders.customer_id` -> `customers.customer_id` (100% validé)
- `order_items.order_id` -> `orders.order_id` (100% validé)
- `order_items.product_id` -> `products.product_id` (100% validé)
- `order_items.seller_id` -> `sellers.seller_id` (100% validé)
- `order_payments.order_id` -> `orders.order_id` (100% validé)
- `order_reviews.order_id` -> `orders.order_id` (100% validé)

Validation automatisée disponible via le fichier de test :
```bash
pytest tests/test_sample_integrity.py -v
```
