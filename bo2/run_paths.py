"""Resolve validated selections without importing the user interface."""
import json
import re
from pathlib import Path


def selected_folder(root, task):
    root = Path(root)
    pointer = root / f"{task}_current_test.json"
    if pointer.exists():
        value = json.loads(pointer.read_text(encoding="utf-8")).get("folder", "")
        if not re.fullmatch(rf"{task}_tests/[0-9a-f]{{32}}/{task}", value):
            raise ValueError("Invalid test selection")
        target = root / value
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Test selection escapes the run directory")
        return target
    return root / task


def lineage_folder(root):
    """Keep an older graph snapshot when the lineage builder format advances."""
    from etl.models import LINEAGE_VERSION
    base=selected_folder(root,"etl").parent/"lineage"
    graph=base/"lineage.json"
    from bo2.artifact_io import read_artifact_text
    if graph.is_file() and json.loads(read_artifact_text(graph)).get("lineage_version")!=LINEAGE_VERSION:
        return base.with_name("lineage_v"+LINEAGE_VERSION.replace(".","_"))
    return base
