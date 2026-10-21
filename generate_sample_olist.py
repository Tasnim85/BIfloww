"""generate_sample_olist.py -- Generate a clean 500-order synthetic Olist dataset across all 8 tables.

Maintains 100% referential integrity across all foreign keys.
Clearly labelled SYNTHETIC.
"""
from __future__ import annotations

import csv
import hashlib
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

OUT_DIR = Path("data/sample")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Generate 500 orders
NUM_ORDERS = 500
NUM_CUSTOMERS = 420  # Some repeat customers
NUM_SELLERS = 40
NUM_PRODUCTS = 120

def make_uuid(prefix: str, idx: int) -> str:
    h = hashlib.md5(f"{prefix}_{idx}".encode()).hexdigest()
    return f"{h[:8]}{h[8:12]}{h[12:16]}{h[16:20]}{h[20:32]}"

BRAZIL_STATES = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "PE", "CE"]
CITIES = {
    "SP": ["Sao Paulo", "Campinas", "Santos", "Sao Bernardo"],
    "RJ": ["Rio de Janeiro", "Niteroi", "Petropolis"],
    "MG": ["Belo Horizonte", "Uberlandia", "Contagem"],
    "RS": ["Porto Alegre", "Caxias do Sul"],
    "PR": ["Curitiba", "Londrina", "Maringa"],
    "SC": ["Florianopolis", "Joinville"],
    "BA": ["Salvador", "Feira de Santana"],
    "DF": ["Brasilia"],
    "GO": ["Goiania"],
    "PE": ["Recife"],
    "CE": ["Fortaleza"],
}
CATEGORIES = [
    "beleza_saude", "informatica_acessorios", "cama_mesa_banho",
    "moveis_decoracao", "esporte_lazer", "utilidades_domesticas",
    "telefonia", "relogios_presentes", "brinquedos", "automotivo"
]
PAYMENT_TYPES = ["credit_card", "boleto", "voucher", "debit_card"]
STATUSES = ["delivered", "delivered", "delivered", "delivered", "shipped", "processing", "canceled"]

# 1. Customers
customers = []
for i in range(NUM_CUSTOMERS):
    cid = make_uuid("cust", i)
    c_uniq = make_uuid("uniq", i)
    st = random.choice(BRAZIL_STATES)
    city = random.choice(CITIES[st])
    zip_code = random.randint(1000, 99999)
    customers.append({
        "customer_id": cid,
        "customer_unique_id": c_uniq,
        "customer_zip_code_prefix": f"{zip_code:05d}",
        "customer_city": city,
        "customer_state": st,
    })

# 2. Sellers
sellers = []
for i in range(NUM_SELLERS):
    sid = make_uuid("seller", i)
    st = random.choice(BRAZIL_STATES)
    city = random.choice(CITIES[st])
    zip_code = random.randint(1000, 99999)
    sellers.append({
        "seller_id": sid,
        "seller_zip_code_prefix": f"{zip_code:05d}",
        "seller_city": city,
        "seller_state": st,
    })

# 3. Products
products = []
for i in range(NUM_PRODUCTS):
    pid = make_uuid("prod", i)
    cat = random.choice(CATEGORIES)
    products.append({
        "product_id": pid,
        "product_category_name": cat,
        "product_name_lenght": random.randint(20, 60),
        "product_description_lenght": random.randint(100, 1500),
        "product_photos_qty": random.randint(1, 6),
        "product_weight_g": random.randint(100, 15000),
        "product_length_cm": random.randint(10, 80),
        "product_height_cm": random.randint(10, 80),
        "product_width_cm": random.randint(10, 80),
    })

# 4. Orders
orders = []
start_date = datetime(2017, 1, 1)
for i in range(NUM_ORDERS):
    oid = make_uuid("order", i)
    c = random.choice(customers)
    status = random.choice(STATUSES)
    days_offset = random.randint(0, 580)
    p_time = start_date + timedelta(days=days_offset, hours=random.randint(8, 20), minutes=random.randint(0, 59))
    app_time = p_time + timedelta(hours=random.randint(1, 24)) if status != "canceled" else ""
    carr_time = app_time + timedelta(days=random.randint(1, 3)) if status in ("delivered", "shipped") and app_time else ""
    deliv_time = carr_time + timedelta(days=random.randint(3, 15)) if status == "delivered" and carr_time else ""
    est_date = p_time.date() + timedelta(days=random.randint(15, 30))

    orders.append({
        "order_id": oid,
        "customer_id": c["customer_id"],
        "order_status": status,
        "order_purchase_timestamp": p_time.strftime("%Y-%m-%d %H:%M:%S"),
        "order_approved_at": app_time.strftime("%Y-%m-%d %H:%M:%S") if app_time else "",
        "order_delivered_carrier_date": carr_time.strftime("%Y-%m-%d %H:%M:%S") if carr_time else "",
        "order_delivered_customer_date": deliv_time.strftime("%Y-%m-%d %H:%M:%S") if deliv_time else "",
        "order_estimated_delivery_date": est_date.strftime("%Y-%m-%d"),
    })

# 5. Order items
order_items = []
for o in orders:
    num_items = random.choices([1, 2, 3], weights=[0.8, 0.15, 0.05])[0]
    for seq in range(1, num_items + 1):
        prod = random.choice(products)
        seller = random.choice(sellers)
        price = round(random.uniform(15.0, 450.0), 2)
        freight = round(random.uniform(10.0, 45.0), 2)
        limit_date = (datetime.fromisoformat(o["order_purchase_timestamp"]) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        order_items.append({
            "order_id": o["order_id"],
            "order_item_id": seq,
            "product_id": prod["product_id"],
            "seller_id": seller["seller_id"],
            "shipping_limit_date": limit_date,
            "price": price,
            "freight_value": freight,
        })

# 6. Order payments
order_payments = []
for o in orders:
    # compute total order amount from items
    items_for_order = [it for it in order_items if it["order_id"] == o["order_id"]]
    total_val = round(sum(it["price"] + it["freight_value"] for it in items_for_order), 2)
    ptype = random.choice(PAYMENT_TYPES)
    inst = random.randint(1, 10) if ptype == "credit_card" else 1
    order_payments.append({
        "order_id": o["order_id"],
        "payment_sequential": 1,
        "payment_type": ptype,
        "payment_installments": inst,
        "payment_value": total_val,
    })

# 7. Order reviews
order_reviews = []
for i, o in enumerate(orders):
    if o["order_status"] == "delivered" or random.random() < 0.3:
        rid = make_uuid("rev", i)
        score = random.choices([5, 4, 3, 2, 1], weights=[0.6, 0.18, 0.08, 0.04, 0.1])[0]
        title = "Muito bom" if score >= 4 else ("Atraso na entrega" if score <= 2 else "")
        msg = "Produto excelente, recomendo!" if score >= 4 else ("Nao recebi o produto no prazo" if score <= 2 else "")
        order_reviews.append({
            "review_id": rid,
            "order_id": o["order_id"],
            "review_score": score,
            "review_comment_title": title,
            "review_comment_message": msg,
            "review_creation_date": o["order_purchase_timestamp"][:10],
            "review_answer_timestamp": o["order_purchase_timestamp"],
        })

# 8. Geolocation
geolocation = []
for st in BRAZIL_STATES:
    for city in CITIES[st]:
        for _ in range(5):
            zip_p = random.randint(1000, 99999)
            lat = round(random.uniform(-30.0, -2.0), 6)
            lng = round(random.uniform(-55.0, -35.0), 6)
            geolocation.append({
                "geolocation_zip_code_prefix": f"{zip_p:05d}",
                "geolocation_lat": lat,
                "geolocation_lng": lng,
                "geolocation_city": city,
                "geolocation_state": st,
            })

# Write CSV files
tables = {
    "olist_orders_dataset.csv": orders,
    "olist_customers_dataset.csv": customers,
    "olist_order_items_dataset.csv": order_items,
    "olist_order_payments_dataset.csv": order_payments,
    "olist_order_reviews_dataset.csv": order_reviews,
    "olist_products_dataset.csv": products,
    "olist_sellers_dataset.csv": sellers,
    "olist_geolocation_dataset.csv": geolocation,
}

for filename, rows in tables.items():
    p = OUT_DIR / filename
    with open(p, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generated {filename:35s}: {len(rows)} rows")

print(f"\nTotal orders generated: {len(orders)}")
