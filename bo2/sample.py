"""Build a relationally closed Olist sample, retaining all nine source tables."""
from pathlib import Path

import pandas as pd


def build(source: Path, destination: Path, orders_count: int = 500) -> dict:
    if orders_count < 2:
        raise ValueError("Choose at least two orders")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Sample destination must be empty")
    frames = {}
    for path in source.glob("*.csv"):
        name = path.stem.removeprefix("olist_").removesuffix("_dataset")
        frames[name] = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    orders = frames["orders"].sort_values("order_id").head(orders_count)
    ids = set(orders.order_id)
    frames["orders"] = orders
    for name in ["order_items", "order_payments", "order_reviews"]:
        frames[name] = frames[name][frames[name].order_id.isin(ids)]
    frames["customers"] = frames["customers"][frames["customers"].customer_id.isin(orders.customer_id)]
    for name, column in [("products", "product_id"), ("sellers", "seller_id")]:
        frames[name] = frames[name][frames[name][column].isin(frames["order_items"][column])]
    zips = set(frames["customers"].customer_zip_code_prefix) | set(frames["sellers"].seller_zip_code_prefix)
    frames["geolocation"] = frames["geolocation"][frames["geolocation"].geolocation_zip_code_prefix.isin(zips)].drop_duplicates("geolocation_zip_code_prefix")
    frames["product_category_name_translation"] = frames["product_category_name_translation"][frames["product_category_name_translation"].product_category_name.isin(frames["products"].product_category_name)]
    destination.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        filename = f"olist_{name}_dataset.csv" if name != "product_category_name_translation" else name + ".csv"
        frame.to_csv(destination / filename, index=False)
    return {name: len(frame) for name, frame in frames.items()}
