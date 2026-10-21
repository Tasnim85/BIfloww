# BIFlow Data Contracts Reference — Step 1a

**Module:** Semantic Detection & Foundation  
**Authors:** Malek (Step 1a), Samar (Orchestration)  
**Location:** `contracts/proposals/semantic_contracts.py` & `contracts/intake.py`

---

## 1. Governance Architecture

BIFlow enforces a two-tier contract architecture:
1. **Shared Production Contracts (`contracts/`):** Fixed, shared models used by all agents across team branches.
2. **Specialized Proposal Contracts (`contracts/proposals/`):** Rich domain models providing deep metadata for specific agent responsibilities.

---

## 2. Shared Production Contract: `contracts.intake.ColumnType`

The pipeline uses `contracts.intake.ColumnTypesReport` as the official output of Step 1a (`intake.column_types:run`).

```python
class ColumnType(Contract):
    table: str
    column: str
    semantic_type: SemanticType        # 17 standard values from contracts.common
    confidence: float                  # Heuristic score in [0.0, 1.0]
    pii_candidate: bool                # Authoritative PII flag for Step 2

class ColumnTypesReport(Artifact):
    model: str                         # e.g., "rules@1.1"
    columns: list[ColumnType]
```

---

## 3. Rich Proposal Contract: `contracts.proposals.semantic_contracts`

For detailed metadata exploration, auditing, and future embedding-based similarity (BO1-06), the module provides richer Pydantic v2 contracts inheriting from `contracts.common.Contract` and `contracts.common.Artifact`.

### `SemanticColumn`
Represents comprehensive semantic profiling of a column:
- `source_table`: Table name.
- `column_name`: Column name.
- `technical_type`: Pandas/SQL data type.
- `semantic_group`: Top-level taxonomy group (e.g. `PERSONAL_DATA`).
- `semantic_type`: Specific taxonomy leaf type (e.g. `EMAIL`).
- `semantic_role`: Role enum (`IDENTIFIER`, `MEASURE`, `DIMENSION`, `ATTRIBUTE`).
- `privacy_hint`: `PrivacyHint` enum (`NO_DIRECT_PII_INDICATOR`, `CONTEXT_DEPENDENT`, `POTENTIAL_PII`, `LIKELY_PII`).
- `confidence_score`: Score in `[0.0, 1.0]`.
- `evidence`: List of non-sensitive explanation strings.
- `classification_status`: `MANUAL_REFERENCE`, `AUTOMATIC`, `NEEDS_REVIEW`, or `UNKNOWN`.

### Built-in Validators
- **Privacy Sanitization:** Ensures that the `evidence` field never leaks raw personal identifiers (e.g., regex checks against embedded email addresses).
- **Metric Verification:** `SemanticMetadata` validates that `total_columns`, `classified_columns`, `unknown_columns`, and `review_required_columns` match the actual list of `columns`.

---

## 4. Bridge / Mapping Between Rich and Production Contracts

When `intake.column_types:run` executes, it maps internal taxonomy types to production `SemanticType` values using `_TYPE_MAP`:

```
Taxonomy Leaf Type (65 types) ──> _TYPE_MAP ──> SemanticType (17 values)
Taxonomy Privacy Hint          ──> _PII_TYPES ──> pii_candidate: bool
Confidence Heuristic           ──> [0.0..1.0] ──> confidence: float
```
