# Contract Change Proposal — BIFlow Semantic Detection (BO1 / Malek)

**Author:** Malek  
**Branch:** `BO1/Samar+Malek`  
**Date:** 2026-10-21  
**Status:** PROPOSAL — awaiting team review before any merge into `contracts/`

---

## 1. Summary

This document describes two proposed changes arising from Step 1a (semantic column
classification) work. Neither change modifies any existing `contracts/` file; they are
documented here for team discussion and tracked in `contracts/proposals/`.

---

## 2. Privacy Vocabulary Migration (taxonomy v1.1.0)

### 2.1 Rationale

The taxonomy YAML v1.0.0 used informal levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
that were not aligned with any enum in `contracts/`. The `PrivacyHint` enum defined in
`contracts/proposals/semantic_contracts.py` uses four explicit values with clearer
semantics for downstream agents (especially Ikbel's PII detection step).

### 2.2 Mapping applied (v1.0.0 → v1.1.0)

| Old value  | New value                  | Meaning                                            |
|------------|----------------------------|----------------------------------------------------|
| `LOW`      | `NO_DIRECT_PII_INDICATOR`  | Column name gives no PII signal                    |
| `MEDIUM`   | `CONTEXT_DEPENDENT`        | May be sensitive depending on dataset context      |
| `HIGH`     | `LIKELY_PII`               | Strong PII indicator — Ikbel's agent must inspect  |
| `CRITICAL` | `LIKELY_PII`               | Merged with HIGH; distinction not needed at Step 1 |

> **Note for Ikbel (Ahmed & Ikbel team):** `privacy_hint` is a *hint from the taxonomy*,
> not a PII decision. The final PII classification remains the responsibility of the
> `privacy/` module. No masking or hashing is performed in `intake/`.

### 2.3 Files changed

- `intake/semantic_detection/config/semantic_types.yaml` — taxonomy_version bumped to `1.1.0`
- `intake/semantic_detection/src/taxonomy_validator.py` — `_VALID_PRIVACY_HINTS` updated
- `intake/semantic_detection/tests/test_taxonomy.py` — test_t11 updated to new values
- `intake/semantic_detection/examples/*.json` — example files updated

### 2.4 No change to `contracts/`

The `contracts/common.py` SemanticType enum and `contracts/intake.py` ColumnType are
**unchanged**. PrivacyHint lives exclusively in `contracts/proposals/semantic_contracts.py`.

---

## 3. Proposed Extension to `contracts/intake.ColumnType`

### 3.1 Problem: information loss

The 65-type taxonomy collapses to 17 `SemanticType` values:

| Taxonomy type(s)                            | SemanticType    | Loss |
|---------------------------------------------|-----------------|------|
| COUNTRY, REGION, TIME, PERIOD, HASH_VALUE…  | `OTHER`         | ✗ info lost |
| LATITUDE, LONGITUDE                         | `NUMBER`        | ✗ geo context lost |
| PRICE, PAYMENT_AMOUNT, REVENUE, COST…       | `AMOUNT`        | ✓ acceptable |
| ORDER_ID, PRODUCT_ID, SELLER_ID…            | `ID`            | ✓ acceptable |

The most impactful losses are **COUNTRY/REGION → OTHER** (removes geo context) and
**LATITUDE/LONGITUDE → NUMBER** (removes geospatial signal).

### 3.2 Proposed field

Add an **optional** field to `contracts.intake.ColumnType`:

```python
semantic_type_detail: str | None = Field(
    default=None,
    description=(
        "Finer-grained taxonomy type_id from intake/semantic_detection. "
        "Examples: 'COUNTRY', 'LATITUDE', 'PRODUCT_CATEGORY'. "
        "Optional — downstream agents must handle None gracefully."
    )
)
```

### 3.3 Impact on other teams

| Team                  | Impact                                                  |
|-----------------------|---------------------------------------------------------|
| Ahmed & Ikbel         | Can use `semantic_type_detail == 'LATITUDE'` to skip geo coords in PII masking |
| Rabeb (KPI/analysis)  | Can use `'REVENUE'` / `'COST'` detail for KPI mapping  |
| Tasnim (auditor)      | Richer audit trail for column lineage                   |
| Samar (orchestrator)  | No impact — ColumnType passes through transparently     |

### 3.4 Backwards compatibility

- Field is `Optional[str] = None` — zero breaking change for agents that ignore it.
- `extra="forbid"` on ColumnType means this field must be **added to the model** in
  `contracts/intake.py` before use. This requires a **team PR** and review.
- Until approved, `semantic_type_detail` is only populated in
  `contracts/proposals/semantic_contracts.py::SemanticColumn` (the rich report).

### 3.5 Requested action

1. Team reviews this proposal.
2. If approved: one team member adds `semantic_type_detail: str | None = None` to
   `contracts/intake.py::ColumnType` in a separate PR on `main`.
3. Malek then updates `intake/column_types.py` to populate it.

---

## 4. Validation Note

`python -m contracts.check_contracts` passes on `BO1/Samar+Malek` before and after
all Tâche 3 changes. Verified with `git diff --stat contracts/` = no output (no
changes to `contracts/` directory).


---

## 5. PERSON_ID Privacy Hint Rule — À valider avec Ikbel

### 5.1 Change (taxonomy v1.1.1)

`PERSON_ID` privacy_hint changed from `LIKELY_PII` → `POTENTIAL_PII`.

**Rationale:** The original prompt specification states:
> `customer_id -> PERSON_ID -> POTENTIAL_PII`

A person identifier such as `customer_id` is a surrogate key. On its own it does
not directly reveal personal information — its sensitivity depends on context and
whether it can be linked to other tables. `POTENTIAL_PII` is therefore more accurate
than `LIKELY_PII` (which is reserved for directly identifying columns like EMAIL,
PHONE, PERSON_NAME, PERSONAL_ADDRESS, BIRTH_DATE).

### 5.2 À valider avec Ikbel

> ⚠️ **This rule change requires Ikbel's review before Step 2.** The PII detection
> module (`privacy/`) may use `privacy_hint` to trigger column-level inspection.
> Downgrading `PERSON_ID` from `LIKELY_PII` to `POTENTIAL_PII` means it would no
> longer be in Ikbel's "immediate inspect" tier. Please confirm whether:
> 1. The PII agent should still flag `PERSON_ID` columns for inspection despite
>    `POTENTIAL_PII` hint, or
> 2. `POTENTIAL_PII` is sufficient and the PII agent's own logic handles linkage risk.

### 5.3 Files changed

- `intake/semantic_detection/config/semantic_types.yaml` — `PERSON_ID` hint and `taxonomy_version: "1.1.1"`
- `intake/semantic_detection/tests/test_taxonomy.py` — `test_t11` updated, `test_t06` updated to `"1.1.1"`
