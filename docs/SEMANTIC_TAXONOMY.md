# BIFlow Semantic Taxonomy Specification

**Version:** 1.1.0  
**Owner:** Malek (BO1-06 / Step 1a)  
**Location:** `intake/semantic_detection/config/semantic_types.yaml`

---

## 1. Overview & Objectives

The BIFlow Semantic Taxonomy provides a standardized, hierarchical classification schema for table columns across heterogeneous relational schemas. It bridges raw technical identifiers (e.g. `varchar`, `int64`) to rich semantic representations necessary for automated BI processing.

The taxonomy is organized into **10 top-level groups** containing **65+ semantic leaf types**.

---

## 2. Taxonomy Hierarchy & Groups

| Group ID | Label | Description | Leaf Types Count |
|---|---|---|---|
| `PERSONAL_DATA` | Personal Data | Direct & indirect identifying information for individuals | 7 |
| `FINANCIAL_DATA` | Financial Data | Monetary values, charges, prices, taxes and costs | 8 |
| `TEMPORAL_DATA` | Temporal Data | Dates, timestamps, periods, intervals and years | 7 |
| `GEOGRAPHICAL_DATA` | Geographical Data | Administrative regions, cities, coordinates and postal codes | 7 |
| `BUSINESS_ENTITY_DATA`| Business Entity Data | Primary and foreign business identifiers (order, product, seller) | 6 |
| `CATEGORICAL_DATA` | Categorical Data | Low-cardinality flags, classifications and status codes | 6 |
| `QUANTITATIVE_DATA` | Quantitative Data | Physical measurements, counts, ratios, weights and ratings | 9 |
| `TEXTUAL_DATA` | Textual Data | Free-form notes, descriptions, reviews and comments | 5 |
| `TECHNICAL_DATA` | Technical Data | System hashes, UUIDs, schema versions and file references | 4 |
| `UNKNOWN_DATA` | Unknown / Unclassified | Fallback group for unresolvable columns | 1 |

---

## 3. Naming Conventions

To guarantee consistency and automated validation:
1. **Group IDs:** Strictly `UPPER_SNAKE_CASE` (e.g., `PERSONAL_DATA`, `BUSINESS_ENTITY_DATA`).
2. **Type IDs:** Strictly `UPPER_SNAKE_CASE` (e.g., `PAYMENT_AMOUNT`, `PRODUCT_CATEGORY`).
3. **Column Aliases:** Lowercase strings matching common industry column naming conventions (`snake_case` or abbreviations).

---

## 4. Privacy Hint Levels

Each taxonomy type defines a `privacy_hint` to assist downstream privacy scanning without performing direct masking:

| Level | Definition | Downstream Directive (Ikbel) |
|---|---|---|
| `NO_DIRECT_PII_INDICATOR` | Non-identifying operational or business data (e.g., prices, counts). | Standard processing. |
| `CONTEXT_DEPENDENT` | Potentially identifying when combined with other features (e.g., ZIP prefix, latitude). | Contextual audit recommended. |
| `POTENTIAL_PII` | Quasi-identifiers or indirect IDs (e.g., customer account ID). | Targeted inspection required. |
| `LIKELY_PII` | Direct identifiers (e.g., email address, phone number, person name). | High priority PII inspection & redaction. |

---

## 5. Extensibility Guidelines

The taxonomy is intentionally decoupled from code:
- Adding a new type requires defining a YAML entry under the relevant group with: `type_id`, `label`, `description`, `privacy_hint`, and `column_aliases`.
- All additions are validated via `intake.semantic_detection.src.taxonomy_validator.validate_taxonomy_file`.
