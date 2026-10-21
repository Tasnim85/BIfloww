"""test_examples.py — Validate the JSON example files."""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

from contracts.proposals.semantic_contracts import (
    SemanticMetadata,
)


class TestExampleFiles:
    def test_olist_schema_example_valid_json(self):
        path = EXAMPLES_DIR / "olist_schema_example.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(data, (dict, list))

    def test_semantic_metadata_example_valid(self):
        path = EXAMPLES_DIR / "semantic_metadata_example.json"
        if path.exists():
            report = SemanticMetadata.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            assert report.total_columns == len(report.columns)

    def test_privacy_hints_example_valid_json(self):
        path = EXAMPLES_DIR / "privacy_hints_example.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(data, (dict, list))

    def test_no_real_personal_data_in_examples(self):
        """Scan all example JSON files for suspicious personal data patterns."""
        import re
        email_pattern = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
        for path in EXAMPLES_DIR.glob("*.json"):
            content = path.read_text(encoding="utf-8")
            emails = email_pattern.findall(content)
            # Filter out clearly fake/example emails
            real_emails = [e for e in emails if "example" not in e.lower() and "test" not in e.lower()]
            assert not real_emails, f"Real email found in {path.name}: {real_emails}"
