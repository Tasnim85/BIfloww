# BIFlow Semantic Detection — Step 1a (Malek)

**Scope:** Semantic Foundation — Taxonomy, Data Contracts & Validation  
**Branch:** `BO1/Samar+Malek`  
**Repo:** `https://github.com/Tasnim85/BIfloww.git`

## What This Module Provides

| Component | File | Purpose |
|---|---|---|
| Semantic Taxonomy | `config/semantic_types.yaml` | 10 groups, 65+ types, privacy hints |
| Taxonomy Loader | `src/taxonomy_loader.py` | Query the taxonomy at runtime |
| Taxonomy Validator | `src/taxonomy_validator.py` | Validate YAML structure + group/type pairs |
| Pydantic Contracts | `contracts/proposals/semantic_contracts.py` | `SemanticColumn`, `SemanticMetadata`, `SemanticMatch` |
| Olist Examples | `examples/` | Reference annotations (manual ground truth) |
| Tests | `tests/` | 20+ pytest tests (taxonomy + contracts + examples) |

## What This Module Does NOT Do

- ❌ PII detection / masking / hashing → **Ikbel**
- ❌ Statistical profiling / anomaly detection → **Ahmed**
- ❌ Embedding similarity computation → **Step 2 (future)**
- ❌ Business glossary / KPI catalog → **Rabeb**

## Quick Start

```bash
# From repo root
pip install pyyaml pydantic pytest

# Run Malek's tests
pytest intake/semantic_detection/tests/ -v

# Verify no contract regression
python -m contracts.check_contracts
```

## Taxonomy Structure

```
10 Groups → 65+ Types
PERSONAL_DATA       → EMAIL, PHONE, PERSON_NAME, PERSON_ID, AGE, BIRTH_DATE, PERSONAL_ADDRESS
FINANCIAL_DATA      → PRICE, PAYMENT_AMOUNT, REVENUE, COST, DISCOUNT, TAX, FREIGHT_COST, PROFIT
TEMPORAL_DATA       → DATE, DATETIME, TIME, YEAR, MONTH, DURATION, PERIOD
GEOGRAPHICAL_DATA   → COUNTRY, STATE, CITY, REGION, POSTAL_CODE, LATITUDE, LONGITUDE
BUSINESS_ENTITY_DATA→ ORDER_ID, PRODUCT_ID, SELLER_ID, INVOICE_ID, TRANSACTION_ID, ORGANIZATION_ID
CATEGORICAL_DATA    → STATUS, PRODUCT_CATEGORY, PAYMENT_METHOD, CUSTOMER_SEGMENT, PRIORITY, BOOLEAN_FLAG
QUANTITATIVE_DATA   → QUANTITY, COUNT, WEIGHT, LENGTH, VOLUME, PERCENTAGE, RATE, RATING, NUMERIC_MEASURE
TEXTUAL_DATA        → DESCRIPTION, COMMENT, TITLE, FREE_TEXT, LABEL
TECHNICAL_DATA      → SYSTEM_ID, HASH_VALUE, VERSION, FILE_REFERENCE
UNKNOWN_DATA        → UNKNOWN
```

## Author
**Malek** — BO1-06 Semantic Similarity Detection & Step 1a Column Classification
