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


def level_below(value: float, warn_below: float, problem_below: float | None = None):
    """Status for "lower is worse" metrics: 🔴 below `problem_below`, 🟡 below `warn_below`."""
    from ..models import Status

    if problem_below is not None and value < problem_below:
        return Status.PROBLEM
    if value < warn_below:
        return Status.WARN
    return Status.OK


def level_above(value: float, warn_above: float):
    """Status for "higher is worse" metrics: 🟡 above `warn_above`."""
    from ..models import Status

    return Status.WARN if value > warn_above else Status.OK
