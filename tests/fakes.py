"""Test doubles for the outside world: PowerShell, clock and context."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from winzel.config import load_default_config
from winzel.context import Context

DATA = Path(__file__).parent / "data"


def sample(name: str) -> Any:
    """Sample PowerShell output from tests/data/<name>.json."""
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


class FakePowerShell:
    """Answers each call by its label: a value, an exception to raise, or a callable."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[dict] = []

    def run_json(self, script: str, *, label: str, timeout_s: float) -> Any:
        self.calls.append({"label": label, "timeout_s": timeout_s, "script": script})
        response = self.responses[label]
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response()
        return response


class FixedClock:
    """A clock stopped at a fixed moment; `advance` moves it forward."""

    def __init__(self, moment: datetime = datetime(2026, 10, 31, 14, 30, 0)) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)


def make_context(
    responses: dict[str, Any] | None = None,
    *,
    is_admin: bool = False,
    config: dict | None = None,
    clock: FixedClock | None = None,
) -> Context:
    return Context(
        powershell=FakePowerShell(responses),
        config=config if config is not None else load_default_config(),
        is_admin=is_admin,
        clock=clock or FixedClock(),
    )
