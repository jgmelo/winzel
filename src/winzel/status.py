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
    """E.g. '3 novos (1 aprovado), 1 removido, 2 alterados'."""
    words = {
        ChangeKind.ADDED: ("novo", "novos"),
        ChangeKind.REMOVED: ("removido", "removidos"),
        ChangeKind.CHANGED: ("alterado", "alterados"),
    }
    parts = []
    for kind, (singular, plural) in words.items():
        of_kind = [c for c in changes if c.kind is kind]
        if not of_kind:
            continue
        text = _count(len(of_kind), singular, plural)
        approved = sum(1 for c in of_kind if c.approved)
        if approved:
            text += f" ({_count(approved, 'aprovado', 'aprovados')})"
        parts.append(text)
    return ", ".join(parts)


def format_date(moment: datetime) -> str:
    return moment.strftime("%d/%m/%Y %H:%M")


def inventory_summary(changes: list[Change], base: str, since: str) -> str:
    """E.g. '152 programas — 3 novos, 1 alterado desde a linha de base (31/10/2026 14:30)'."""
    described = describe_changes(changes) or "sem mudanças"
    return f"{base} — {described} desde {since}"
