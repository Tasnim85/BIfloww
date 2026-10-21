"""Count orders at order grain, including explicitly reported unknown dates/statuses."""
import pandas as pd


def coverage(frame, table="orders", date_column="order_purchase_timestamp", status_column="order_status", id_column="order_id"):
    required = [date_column, status_column] + ([id_column] if id_column else [])
    if not set(required).issubset(frame.columns):
        raise ValueError("COVERAGE_COLUMNS: choose the order date, status and identifier columns")
    if id_column and (frame[id_column].isna().any() or frame[id_column].duplicated().any()):
        raise ValueError("COVERAGE_GRAIN: order identifiers must be present and unique; select an order table")
    dates = pd.to_datetime(frame[date_column], errors="coerce", format="mixed", utc=True)
    days = dates.dt.strftime("%Y-%m-%d").where(dates.notna(), None)
    statuses = frame[status_column].astype("string").str.strip().replace("", pd.NA)
    data = pd.DataFrame({"date":days, "status":statuses})
    def counts(columns):
        grouped = data.groupby(columns,dropna=False,sort=True).size().reset_index(name="orders")
        return [{**{col:None if pd.isna(row[col]) else str(row[col]) for col in columns},
                 "orders":int(row["orders"])} for _,row in grouped.iterrows()]
    return {"schema_version":"bo2-local-1", "source_table":table,"date_column":date_column,
            "status_column":status_column,"id_column":id_column,"grain":"order_id" if id_column else "input_row",
            "total_orders":len(frame),"time_zone":"UTC","period_start":None if dates.dropna().empty else dates.min().strftime("%Y-%m-%d"),
            "period_end":None if dates.dropna().empty else dates.max().strftime("%Y-%m-%d"),
            "missing_dates":int(frame[date_column].isna().sum()),
            "invalid_dates":int((frame[date_column].notna() & dates.isna()).sum()),
            "missing_statuses":int(statuses.isna().sum()),
            "orders_by_day":counts(["date"]),"orders_by_status":counts(["status"]),
            "orders_by_day_status":counts(["date","status"])}
