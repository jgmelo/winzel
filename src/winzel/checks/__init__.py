"""Check registry. A new check is a new module here that calls `register`."""

from __future__ import annotations

from ..models import Check

_REGISTRY: dict[str, Check] = {}


def register(check: Check) -> Check:
    if check.id in _REGISTRY:
        raise ValueError(f"checagem duplicada: {check.id}")
    _REGISTRY[check.id] = check
    return check


def all_checks() -> list[Check]:
    _load_builtin()
    return list(_REGISTRY.values())


def get_check(check_id: str) -> Check:
    _load_builtin()
    return _REGISTRY[check_id]


def _load_builtin() -> None:
    from . import programs, startup  # noqa: F401  (modules register themselves)
