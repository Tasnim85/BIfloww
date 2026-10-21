"""taxonomy_validator.py — Validate taxonomy YAML structure and semantic metadata.

Responsibilities:
  1. Verify YAML structure (groups, types, required fields).
  2. Check type_id uniqueness across all groups.
  3. Validate group↔type relationships.
  4. Detect missing descriptions.
  5. Verify taxonomy version.
  6. Return explicit error messages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ValidationResult:
    """Outcome of a taxonomy or metadata validation."""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


_REQUIRED_GROUPS = {
    "PERSONAL_DATA", "FINANCIAL_DATA", "TEMPORAL_DATA",
    "GEOGRAPHICAL_DATA", "BUSINESS_ENTITY_DATA", "CATEGORICAL_DATA",
    "QUANTITATIVE_DATA", "TEXTUAL_DATA", "TECHNICAL_DATA", "UNKNOWN_DATA",
}

_VALID_PRIVACY_HINTS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def validate_taxonomy_file(yaml_path: Path | str) -> ValidationResult:
    """Full validation of a semantic_types.yaml file."""
    result = ValidationResult()
    path = Path(yaml_path)

    # 1. File exists and is readable
    if not path.exists():
        result.add_error(f"Taxonomy file not found: {path}")
        return result

    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        result.add_error(f"YAML parse error: {exc}")
        return result

    if not isinstance(data, dict):
        result.add_error("Root element must be a YAML mapping.")
        return result

    # 2. Version check
    version = data.get("taxonomy_version")
    if not version:
        result.add_error("Missing required field: taxonomy_version")
    else:
        result.stats["taxonomy_version"] = version

    # 3. Groups check
    groups = data.get("groups")
    if not groups or not isinstance(groups, list):
        result.add_error("Missing or invalid 'groups' list.")
        return result

    found_groups: set[str] = set()
    all_type_ids: list[str] = []
    type_to_group: dict[str, str] = {}
    total_types = 0

    for i, group in enumerate(groups):
        gid = group.get("group_id")
        if not gid:
            result.add_error(f"Group at index {i} is missing 'group_id'.")
            continue

        # Uniqueness
        if gid in found_groups:
            result.add_error(f"Duplicate group_id: {gid}")
        found_groups.add(gid)

        # UPPER_SNAKE_CASE
        if gid != gid.upper():
            result.add_error(f"Group '{gid}' is not UPPER_SNAKE_CASE.")

        # Description
        if not group.get("description"):
            result.add_warning(f"Group '{gid}' has no description.")

        # Types
        types = group.get("types", [])
        if not types:
            result.add_warning(f"Group '{gid}' has no types defined.")

        for j, tdef in enumerate(types):
            tid = tdef.get("type_id")
            if not tid:
                result.add_error(f"Type at index {j} in group '{gid}' is missing 'type_id'.")
                continue

            # Uniqueness
            if tid in type_to_group:
                result.add_error(
                    f"Duplicate type_id '{tid}': found in '{type_to_group[tid]}' and '{gid}'."
                )
            type_to_group[tid] = gid
            all_type_ids.append(tid)

            # UPPER_SNAKE_CASE
            if tid != tid.upper():
                result.add_error(f"Type '{tid}' is not UPPER_SNAKE_CASE.")

            # Description
            if not tdef.get("description"):
                result.add_warning(f"Type '{tid}' in group '{gid}' has no description.")

            # Privacy hint
            ph = tdef.get("privacy_hint")
            if ph and ph not in _VALID_PRIVACY_HINTS:
                result.add_error(
                    f"Type '{tid}' has invalid privacy_hint '{ph}'. "
                    f"Must be one of: {_VALID_PRIVACY_HINTS}"
                )

            total_types += 1

    # 4. Required groups present
    missing_groups = _REQUIRED_GROUPS - found_groups
    if missing_groups:
        result.add_error(f"Missing required groups: {sorted(missing_groups)}")

    # 5. Stats
    result.stats.update({
        "total_groups": len(found_groups),
        "total_types": total_types,
        "unique_type_ids": len(set(all_type_ids)),
        "groups_found": sorted(found_groups),
    })

    return result


def validate_group_type_pair(
    group_id: str, type_id: str, taxonomy_data: dict[str, Any]
) -> ValidationResult:
    """Check if a group_id/type_id pair is valid according to taxonomy_data."""
    result = ValidationResult()
    groups = taxonomy_data.get("groups", [])

    # Build lookup
    valid_pairs: dict[str, set[str]] = {}
    for g in groups:
        gid = g.get("group_id", "")
        valid_pairs[gid] = {t.get("type_id", "") for t in g.get("types", [])}

    if group_id not in valid_pairs:
        result.add_error(f"Unknown group: '{group_id}'")
        return result

    if type_id not in valid_pairs[group_id]:
        all_types = {tid for types in valid_pairs.values() for tid in types}
        if type_id in all_types:
            # Find the real group
            real_group = next(
                gid for gid, types in valid_pairs.items() if type_id in types
            )
            result.add_error(
                f"Type '{type_id}' does not belong to group '{group_id}'. "
                f"It belongs to '{real_group}'."
            )
        else:
            result.add_error(f"Unknown type: '{type_id}'")

    return result
