"""Bounded comparisons of protected inputs with cleaned outputs."""
import json
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq


def preview(path, limit=100):
    file = pq.ParquetFile(path)
    batch = next(file.iter_batches(batch_size=limit), None)
    return batch.to_pandas() if batch is not None else file.schema_arrow.empty_table().to_pandas()


def visible(value):
    if pd.isna(value):
        return "Vide"
    if isinstance(value, str):
        return "« " + value.replace(" ", "·").replace("\n", "↵").replace("\t", "⇥") + " »"
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    return str(value)


def kind(series):
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "Date"
    if pd.api.types.is_bool_dtype(series.dtype):
        return "Vrai / Faux"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "Nombre"
    return "Texte"


def comparison(source, cleaned, table, limit=100):
    source, cleaned = Path(source), Path(cleaned)
    original = source / f"{table}.parquet"
    output = cleaned / "tables" / f"{table}.parquet"
    meta_before, meta_after = pq.ParquetFile(original).metadata, pq.ParquetFile(output).metadata
    size = sum(meta.row_group(i).total_byte_size for meta in (meta_before,meta_after) for i in range(meta.num_row_groups))
    sampled = size > 32 * 1024 * 1024
    before = preview(original,limit) if sampled else pd.read_parquet(original)
    after = preview(output,limit) if sampled else pd.read_parquet(output)
    mapping_path = cleaned / "row_mapping.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")).get(table) if mapping_path.exists() else None
    if mapping is None and meta_before.num_rows == meta_after.num_rows:
        mapping = list(range(meta_after.num_rows))
    aligned = mapping is not None
    if aligned and (len(mapping) != meta_after.num_rows or len(set(mapping)) != len(mapping)
                    or any(type(i) is not int or i < 0 or i >= meta_before.num_rows for i in mapping)):
        raise ValueError("Invalid source row mapping")
    details, count, removed = [], 0, pd.DataFrame()
    if aligned:
        indices = [(i, old) for i, old in enumerate(mapping[:len(after)]) if old < len(before)]
        old_indices = [old for _,old in indices]
        new_indices = [new for new,_ in indices]
        left = before.iloc[old_indices].reset_index(drop=True)
        right = after.iloc[new_indices].reset_index(drop=True)
        for column in before.columns.intersection(after.columns):
            equal = left[column].eq(right[column]).fillna(False) | (left[column].isna() & right[column].isna())
            # Pandas can consider a date string equal to its parsed timestamp.
            # Its newly recognized type is still a meaningful cleaning change.
            if kind(left[column]) != kind(right[column]):
                equal &= left[column].isna() & right[column].isna()
            changed = ~equal
            count += int(changed.sum())
            for position in changed[changed].index[:max(0,limit-len(details))]:
                details.append({"Ligne d’origine": old_indices[position]+1, "Information": column,
                                "Avant": visible(left[column].iloc[position]), "Après": visible(right[column].iloc[position])})
        kept = set(mapping)
        removed = before.iloc[[i for i in range(len(before)) if i not in kept][:limit]]
    return {"before":before.head(limit), "after":after.head(limit), "details":pd.DataFrame(details),
            "changed":count if aligned else None,"removed":removed,"sampled":sampled,
            "aligned":aligned,"rows_before":meta_before.num_rows,"rows_after":meta_after.num_rows}
