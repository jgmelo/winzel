"""Context: everything a check needs from the outside world (dependency injection)."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .powershell import PowerShell, PowerShellRunner


@dataclass
class Context:
    powershell: PowerShellRunner
    config: dict
    is_admin: bool
    clock: Callable[[], datetime]

    def now(self) -> datetime:
        return self.clock().replace(microsecond=0)


def detect_is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except AttributeError:
        return hasattr(os, "geteuid") and os.geteuid() == 0


def production_context(config: dict) -> Context:
    return Context(
        powershell=PowerShell(),
        config=config,
        is_admin=detect_is_admin(),
        clock=datetime.now,
    )
