"""Inventory status and one-line summaries derived from a diff."""

from __future__ import annotations

from datetime import datetime

from .diff import Change, ChangeKind
from .models import Status


def inventory_status(changes: list[Change]) -> Status:
    """🟢 without added/removed since the reference; 🟡 otherwise. Changed is informative."""
    return Status.WARN if any(c.affects_status for c in changes) else Status.OK


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def describe_changes(changes: list[Change]) -> str:
    added = sum(1 for c in changes if c.kind is ChangeKind.ADDED)
    removed = sum(1 for c in changes if c.kind is ChangeKind.REMOVED)
    changed = sum(1 for c in changes if c.kind is ChangeKind.CHANGED)
    parts = []
    if added:
        parts.append(_count(added, "novo", "novos"))
    if removed:
        parts.append(_count(removed, "removido", "removidos"))
    if changed:
        parts.append(_count(changed, "alterado", "alterados"))
    return ", ".join(parts)


def format_date(moment: datetime) -> str:
    return moment.strftime("%d/%m/%Y %H:%M")


def inventory_summary(changes: list[Change], base: str, reference_at: datetime | None) -> str:
    """E.g. '152 programas — 3 novos, 1 alterado desde a linha de base (31/10/2026 14:30)'."""
    if reference_at is None:
        return f"{base} — linha de base registrada agora"
    since = f"desde a linha de base ({format_date(reference_at)})"
    described = describe_changes(changes) or "sem mudanças"
    return f"{base} — {described} {since}"
