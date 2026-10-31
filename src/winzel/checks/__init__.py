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
    """Registered checks: built-in ones in BUILTIN order, then any others."""
    _load_builtin()
    order = {name: i for i, name in enumerate(BUILTIN)}
    return sorted(_REGISTRY.values(), key=lambda c: order.get(c.id, len(order)))


def get_check(check_id: str) -> Check:
    _load_builtin()
    return _REGISTRY[check_id]


# Display order: as listed here.
BUILTIN = [
    "programs",
    "store_apps",
    "startup",
    "scheduled_tasks",
    "services",
    "pip_global",
    "wsl_distros",
    "disk_c",
    "dev_drive",
    "clutter",
    "battery",
    "ssd",
]


def _load_builtin() -> None:
    from importlib import import_module

    for name in BUILTIN:  # modules register themselves on import
        import_module(f"{__name__}.{name}")
