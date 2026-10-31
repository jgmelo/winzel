"""Differences between two sets of inventory items (SPEC, seção 6.2)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import Item


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"

    @property
    def symbol(self) -> str:
        return {"added": "➕", "removed": "➖", "changed": "🔄"}[self.value]

    @property
    def text_symbol(self) -> str:
        return {"added": "+", "removed": "-", "changed": "~"}[self.value]

    @property
    def label(self) -> str:
        return {"added": "adicionado", "removed": "removido", "changed": "alterado"}[self.value]


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    category: str
    key: str
    name: str
    old_version: str | None
    new_version: str | None

    @property
    def affects_status(self) -> bool:
        """Only added and removed count for the inventory status; changed is informative."""
        return self.kind in (ChangeKind.ADDED, ChangeKind.REMOVED)


_ORDER = {ChangeKind.ADDED: 0, ChangeKind.REMOVED: 1, ChangeKind.CHANGED: 2}


def diff_items(reference: dict[str, Item], current: dict[str, Item]) -> list[Change]:
    """Added: only in current. Removed: only in reference. Changed: same key, other version."""
    changes = []
    for key, item in current.items():
        old = reference.get(key)
        if old is None:
            changes.append(
                Change(ChangeKind.ADDED, item.category, key, item.display_name, None, item.version)
            )
        elif old.version != item.version:
            changes.append(
                Change(
                    ChangeKind.CHANGED,
                    item.category,
                    key,
                    item.display_name,
                    old.version,
                    item.version,
                )
            )
    for key, old in reference.items():
        if key not in current:
            changes.append(
                Change(ChangeKind.REMOVED, old.category, key, old.display_name, old.version, None)
            )
    return sorted(changes, key=lambda c: (_ORDER[c.kind], c.name.lower(), c.key))
