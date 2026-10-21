"""Select compatible playbooks by numeric version, never modification time."""
import re
import json
from pathlib import Path
import yaml
from .llm_rules import Proposal, validate_approval


def load_playbook(path):
    from bo2.artifact_io import details_path
    path=Path(path)
    private=details_path(path)
    text = (private if private.is_file() else path).read_text(encoding="utf-8")
    # Read historical YAML results for compatibility; all new files are JSON.
    return json.loads(text) if Path(path).suffix.lower() == ".json" else yaml.safe_load(text)


def schema(frames):
    return {name: sorted(frame.columns.tolist()) for name, frame in sorted(frames.items())}


def compatible(book, frames):
    if "rules" in book:
        return book.get("input_schema") == schema(frames)
    if not book.get("required_tables") or not set(book["required_tables"]).issubset(frames):
        return False
    for section in ("numeric_columns", "date_columns", "required_values", "critical_nonnegative_columns"):
        for table, columns in book.get(section, {}).items():
            if table in frames and not set(columns).issubset(frames[table].columns):
                return False
    return True


def select(frames, directory, runs):
    paths = sorted(set(path for extension in ("json", "yaml", "yml")
        for path in [*Path(directory).glob(f"*.{extension}"),
                     *Path(runs).glob(f"*/cleaning/*.{extension}"),
                     *Path(runs).glob(f"*/cleaning_tests/*/cleaning/*.{extension}")]))
    candidates = []
    for path in paths:
        if path.name.endswith('.bo2.json'):
            continue
        book = load_playbook(path)
        if not isinstance(book, dict) or not {"name", "version"}.issubset(book) or not compatible(book, frames):
            continue
        if not re.fullmatch(r"\d+\.\d+", str(book.get("version", ""))):
            raise ValueError("Invalid compatible playbook version")
        if "rules" in book:
            proposal = Proposal.model_validate({key: book[key] for key in ("name", "version", "rules")})
            validate_approval(proposal, book.get("approval", {}))
        candidates.append((book, path))
    if not candidates:
        return None
    # Different families cannot be ordered by their unrelated version numbers.
    exact = [entry for entry in candidates if "rules" in entry[0]]
    candidates = exact or candidates
    if len({book["name"] for book, _ in candidates}) != 1:
        raise ValueError("Several compatible playbook families require explicit selection")
    latest = max(tuple(map(int, book["version"].split("."))) for book, _ in candidates)
    winners = [(book, path) for book, path in candidates if tuple(map(int, book["version"].split("."))) == latest]
    def content(book):
        return {key: value for key, value in book.items() if key != "approval"}
    if any(content(book) != content(winners[0][0]) for book, _ in winners[1:]):
        raise ValueError("Conflicting playbooks share the latest version")
    return winners[0]


def metadata(frames):
    return {"tables": {name: {"rows": len(frame), "columns": {
        column: {"dtype": str(frame[column].dtype), "missing": int(frame[column].isna().sum()),
                 "distinct": int(frame[column].nunique())} for column in frame.columns}}
        for name, frame in frames.items()}}
