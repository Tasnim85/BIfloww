# BIFlow — Synthetic Olist Sample Data

> [!IMPORTANT]
> **Ces fichiers CSV sont SYNTHÉTIQUES (générés). Ils ne contiennent aucune donnée personnelle réelle.**
> Ils sont fournis à des fins de test et de démonstration du pipeline BIFlow uniquement.

## Objectif

Ce jeu d'échantillons simule la structure du jeu de données e-commerce brésilien Olist,
utilisé comme entrée de test standard pour le pipeline BIFlow (`BO1/Samar+Malek`).

## Fichiers

| Fichier | Lignes | Description |
|---------|--------|-------------|
| `olist_orders_dataset.csv` | 50 | Commandes avec horodatages et statut |
| `olist_customers_dataset.csv` | 50 | Données clients synthétiques |
| `olist_order_payments_dataset.csv` | 60 | Paiements (certaines commandes en ont plusieurs) |

## Schéma

### olist_orders_dataset.csv
- `order_id` — UUID (lié aux paiements)
- `customer_id` — UUID (lié aux clients)
- `order_status` — delivered / shipped / processing / cancelled
- `order_purchase_timestamp` — datetime ISO 8601
- `order_approved_at` — datetime ISO 8601 (nullable)
- `order_delivered_carrier_date` — datetime ISO 8601 (nullable)
- `order_delivered_customer_date` — datetime ISO 8601 (nullable)
- `order_estimated_delivery_date` — date ISO 8601

### olist_customers_dataset.csv
- `customer_id` — UUID (FK vers orders)
- `customer_unique_id` — UUID
- `customer_zip_code_prefix` — entier 5 chiffres
- `customer_city` — nom de ville brésilienne synthétique
- `customer_state` — code état brésilien (2 lettres)

### olist_order_payments_dataset.csv
- `order_id` — UUID (FK vers orders)
- `payment_sequential` — numéro séquentiel par commande (commence à 1)
- `payment_type` — credit_card / boleto / voucher / debit_card
- `payment_installments` — nombre de mensualités (1–12)
- `payment_value` — montant en BRL (float)

## Utilisation

```python
import pandas as pd
from pathlib import Path

sample_dir = Path("data/sample")
orders    = pd.read_csv(sample_dir / "olist_orders_dataset.csv")
customers = pd.read_csv(sample_dir / "olist_customers_dataset.csv")
payments  = pd.read_csv(sample_dir / "olist_order_payments_dataset.csv")

print(f"Orders: {len(orders)}, Customers: {len(customers)}, Payments: {len(payments)}")
```

## Note sur le réalisme

- Tous les UUID sont générés aléatoirement (aucune donnée client réelle).
- Les noms de villes et codes d'état sont de vrais noms brésiliens, mais les combinaisons sont aléatoires.
- Les montants de paiement sont dans une plage BRL réaliste (R\$12–R\$1 850).
- Les horodatages couvrent 2017-01-01 à 2018-08-31 (correspond à la plage de dates Olist réelle).
