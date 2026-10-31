"""Helpers shared by checks."""

from __future__ import annotations

from typing import Any


def as_list(value: Any) -> list:
    """PowerShell's ConvertTo-Json turns 1-element arrays into objects and empty into null."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def plural(count: int, singular: str, plural_form: str) -> str:
    return f"{count} {singular if count == 1 else plural_form}"
