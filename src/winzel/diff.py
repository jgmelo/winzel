"""Differences between two sets of inventory items (SPEC, seção 6.2)."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    approved: bool = False
    approval_reason: str = ""

    @property
    def approvable(self) -> bool:
        """Only added and removed can be approved; changed is informative."""
        return self.kind in (ChangeKind.ADDED, ChangeKind.REMOVED)

    @property
    def affects_status(self) -> bool:
        """Only unapproved added and removed count for the inventory status."""
        return self.approvable and not self.approved

    @property
    def approval_key(self) -> tuple[str, str, str]:
        return (self.category, self.key, self.kind.value)


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


def apply_approvals(changes: list[Change], approvals: dict) -> list[Change]:
    """Mark changes approved for (category, key, kind), in any version (SPEC 6.2).

    An item approved as added that is later removed is a new, unapproved change.
    """
    result = []
    for change in changes:
        approval = approvals.get(change.approval_key) if change.approvable else None
        if approval is not None:
            change = replace(change, approved=True, approval_reason=approval.reason)
        result.append(change)
    return result
