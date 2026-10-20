"""Recommend a supported physical layout from metadata, not generated SQL."""
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bo2.local_llm import request_json

SchemaType = Literal["star", "snowflake", "constellation"]


class SchemaComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    star: str = Field(min_length=1)
    snowflake: str = Field(min_length=1)
    constellation: str = Field(min_length=1)


class SchemaRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_type: SchemaType
    rationale: str = Field(min_length=1)
    alternatives: SchemaComparison
    validation_basis: Literal["metadata_not_benchmark"] = "metadata_not_benchmark"


def recommend(frames: dict, workload: str, model: str | None = None) -> SchemaRecommendation:
    metadata = {
        "workload": workload,
        "hard_requirements": ["Keep order-item and order-payment grains separate", "Preserve every payment and its amount", "Keep six canonical table names available to teammates"],
        "verified_structural_facts": {
            "constellation": {"physical_tables": 6, "dimensions_are_flat": True, "dimensions_are_shared": True, "duplicated_customer_and_date_rows": 0},
            "star": {"physical_tables": 8, "dimensions_are_flat": True, "independent_marts": True, "extra_customer_dimension_rows": len(frames["customers"]), "date_dimension_is_also_duplicated": True},
            "snowflake": {"physical_tables": 8, "normalizes_states_and_categories": True, "extra_dimension_joins": True},
            "comparison_limits": "Star and constellation have the same joins per fact for equivalent queries: both use flat dimensions. Constellation does NOT reconstruct normalized dimensions. No query speed or storage byte measurements are available. Snowflake can reduce repeated dimension attributes but needs extra dimension joins.",
        },
        "implementations": {
            "constellation": "Two facts sharing customer/date dimensions; product/seller dimensions on items. Six physical tables, least duplicated dimensions.",
            "star": "Two independent star marts in items_mart and payments_mart with separate customer/date copies. Canonical compatibility views expose the six shared names.",
            "snowflake": "Two facts with normalized state and product-category dimensions and base customer/product/seller tables. Canonical compatibility views reconstruct flat dimensions.",
        },
        "tables": {name: {"rows": len(frame), "columns": {col: {"dtype": str(frame[col].dtype), "missing": int(frame[col].isna().sum()), "distinct": int(frame[col].nunique())} for col in frame}} for name, frame in frames.items()},
    }
    response = request_json("You advise on analytical warehouse design. Compare all three supported layouts and select the one most appropriate for these Olist metadata and workload. Respect all hard requirements and verified_structural_facts, which override general knowledge. In particular constellation has FLAT shared dimensions and the SAME joins per fact as independent stars. Explain the choice using structural facts and workload only. Do not claim any design is faster or uses fewer storage bytes: no benchmarks exist. Return exactly one alternative per schema type and no SQL.", metadata, SchemaRecommendation, model or os.environ.get("OLLAMA_MODEL", "llama3:latest"))
    return response
