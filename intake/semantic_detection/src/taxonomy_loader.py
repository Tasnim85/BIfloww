"""taxonomy_loader.py — Load and query the BIFlow semantic taxonomy.

Responsibilities:
  - Load semantic_types.yaml from disk.
  - Parse the hierarchical group/type structure.
  - Provide fast lookups: group_ids, type_ids, type→group mapping, aliases.
  - Return structured representations for downstream agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# Default path: config/ sits next to src/
_DEFAULT_YAML = Path(__file__).resolve().parent.parent / "config" / "semantic_types.yaml"


@dataclass(frozen=True)
class SemanticTypeInfo:
    """One leaf in the taxonomy tree."""
    type_id: str
    label: str
    description: str
    privacy_hint: str
    group_id: str
    column_aliases: list[str] = field(default_factory=list)
    patterns: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticGroupInfo:
    """One branch in the taxonomy tree."""
    group_id: str
    label: str
    description: str
    types: list[SemanticTypeInfo] = field(default_factory=list)


class TaxonomyLoader:
    """Load, index and query a BIFlow semantic taxonomy YAML file."""

    def __init__(self, yaml_path: Path | str = _DEFAULT_YAML) -> None:
        self._path = Path(yaml_path)
        self._raw: dict[str, Any] = {}
        self._groups: dict[str, SemanticGroupInfo] = {}
        self._types: dict[str, SemanticTypeInfo] = {}
        self._alias_index: dict[str, str] = {}  # alias → type_id
        self._type_to_group: dict[str, str] = {}  # type_id → group_id
        self._load()

    # ── public properties ────────────────────────────────────────────────
    @property
    def version(self) -> str:
        return self._raw.get("taxonomy_version", "unknown")

    @property
    def name(self) -> str:
        return self._raw.get("taxonomy_name", "unknown")

    @property
    def group_ids(self) -> list[str]:
        return list(self._groups.keys())

    @property
    def type_ids(self) -> list[str]:
        return list(self._types.keys())

    @property
    def groups(self) -> dict[str, SemanticGroupInfo]:
        return dict(self._groups)

    @property
    def types(self) -> dict[str, SemanticTypeInfo]:
        return dict(self._types)

    # ── public methods ───────────────────────────────────────────────────
    def get_group(self, group_id: str) -> SemanticGroupInfo | None:
        """Return a group by its ID, or None."""
        return self._groups.get(group_id)

    def get_type(self, type_id: str) -> SemanticTypeInfo | None:
        """Return a type by its ID, or None."""
        return self._types.get(type_id)

    def group_for_type(self, type_id: str) -> str | None:
        """Return the group_id that owns *type_id*, or None."""
        return self._type_to_group.get(type_id)

    def types_in_group(self, group_id: str) -> list[SemanticTypeInfo]:
        """All types belonging to *group_id*."""
        g = self._groups.get(group_id)
        return list(g.types) if g else []

    def type_id_from_alias(self, alias: str) -> str | None:
        """Resolve a column alias to its type_id, or None."""
        return self._alias_index.get(alias.lower().strip())

    def is_valid_group(self, group_id: str) -> bool:
        return group_id in self._groups

    def is_valid_type(self, type_id: str) -> bool:
        return type_id in self._types

    def is_valid_pair(self, group_id: str, type_id: str) -> bool:
        """Return True only if type_id belongs to group_id."""
        return self._type_to_group.get(type_id) == group_id

    def privacy_hint_for(self, type_id: str) -> str | None:
        """Return the privacy_hint of a type, or None."""
        t = self._types.get(type_id)
        return t.privacy_hint if t else None

    def summary(self) -> dict[str, Any]:
        """Return a compact summary dict."""
        return {
            "taxonomy_version": self.version,
            "taxonomy_name": self.name,
            "total_groups": len(self._groups),
            "total_types": len(self._types),
            "total_aliases": len(self._alias_index),
            "groups": {
                gid: [t.type_id for t in g.types]
                for gid, g in self._groups.items()
            },
        }

    # ── private ──────────────────────────────────────────────────────────
    def _load(self) -> None:
        with open(self._path, encoding="utf-8") as fh:
            self._raw = yaml.safe_load(fh)

        for group_data in self._raw.get("groups", []):
            gid = group_data["group_id"]
            type_infos: list[SemanticTypeInfo] = []
            for td in group_data.get("types", []):
                ti = SemanticTypeInfo(
                    type_id=td["type_id"],
                    label=td.get("label", td["type_id"]),
                    description=td.get("description", ""),
                    privacy_hint=td.get("privacy_hint", "LOW"),
                    group_id=gid,
                    column_aliases=td.get("column_aliases", []),
                    patterns=td.get("patterns", []),
                )
                type_infos.append(ti)
                self._types[ti.type_id] = ti
                self._type_to_group[ti.type_id] = gid
                for alias in ti.column_aliases:
                    self._alias_index[alias.lower().strip()] = ti.type_id

            gi = SemanticGroupInfo(
                group_id=gid,
                label=group_data.get("label", gid),
                description=group_data.get("description", ""),
                types=type_infos,
            )
            self._groups[gid] = gi
