"""compare_step1_step2.py -- Compare classification outputs of Step 1a vs Step 2 on data/sample.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BIFLOW_B = REPO_ROOT.parent / "biflow-B"

sys.path.insert(0, str(REPO_ROOT))
from intake.column_types import _classify_column

import intake.semantic_detection
intake.semantic_detection.__path__.append(str(BIFLOW_B / "intake" / "semantic_detection"))

from intake.semantic_detection.step2.rule_classifier import RuleBasedClassifier
from intake.semantic_detection.step2.schema_reader import read_schema_dir
from intake.semantic_detection.step2.pipeline import _TYPE_MAP as STEP2_TYPE_MAP, _PII_TAXONOMY_TYPES as STEP2_PII_TYPES

sample_dir = REPO_ROOT / "data" / "sample"
classifier_s2 = RuleBasedClassifier(
    rules_yaml=BIFLOW_B / "intake" / "semantic_detection" / "config" / "classification_rules.yaml",
    taxonomy_yaml=BIFLOW_B / "intake" / "semantic_detection" / "config" / "semantic_types.yaml",
)

tables_s2 = read_schema_dir(sample_dir)
results_s2 = classifier_s2.classify_tables(tables_s2)
s2_map = {(r.table, r.column): r for r in results_s2}

print("=" * 105)
print(f"{'TABLE':<32} {'COLUMN':<32} {'STEP 1a (PII)':<20} {'STEP 2 (PII)':<20}")
print("=" * 105)

total_columns = 0
matches = 0
mismatches = []

for table_schema in sorted(tables_s2, key=lambda t: t.table):
    tname = table_schema.table
    for col_schema in table_schema.columns:
        col = col_schema.column
        total_columns += 1

        s1 = _classify_column(tname, col)
        s1_type = s1.semantic_type.value
        s1_pii = s1.pii_candidate

        res2 = s2_map.get((tname, col))
        if res2:
            s2_sem_type = STEP2_TYPE_MAP.get(res2.semantic_type, res2.semantic_type)
            s2_type = s2_sem_type.value if hasattr(s2_sem_type, "value") else str(s2_sem_type)
            s2_pii = res2.semantic_type in STEP2_PII_TYPES
            tier = res2.match_tier
            conf = res2.confidence
        else:
            s2_type, s2_pii, tier, conf = "MISSING", False, "none", 0.0

        is_match = (s1_type == s2_type and s1_pii == s2_pii)
        if is_match:
            matches += 1
        else:
            mismatches.append((tname, col, s1_type, s1_pii, s2_type, s2_pii, tier, conf))

        flag = " " if is_match else "*"
        s1_str = f"{s1_type} {'(PII)' if s1_pii else ''}"
        s2_str = f"{s2_type} {'(PII)' if s2_pii else ''}"
        print(f"{flag} {tname:<30} {col:<32} {s1_str:<20} {s2_str:<20}")

print("=" * 105)
print(f"Total Columns Analyzed : {total_columns}")
print(f"Exact Agreement        : {matches}/{total_columns} ({matches/total_columns*100:.1f}%)")
print(f"Differences            : {len(mismatches)}")
print("=" * 105)

if mismatches:
    print("\nDetailed Discrepancies (Step 1a vs Step 2):")
    for t, c, s1_t, s1_p, s2_t, s2_p, tier, conf in mismatches:
        print(f"  * {t}.{c}:")
        print(f"      Step 1a: semantic_type={s1_t}, pii_candidate={s1_p}")
        print(f"      Step 2 : semantic_type={s2_t}, pii_candidate={s2_p} (tier={tier}, confidence={conf:.2f})")
