"""Test doubles for the outside world: PowerShell, commands, clock and context."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from winzel.commands import CommandResult
from winzel.config import load_default_config
from winzel.context import Context

DATA = Path(__file__).parent / "data"


def sample(name: str) -> Any:
    """Sample PowerShell output from tests/data/<name>.json."""
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


class FakePowerShell:
    """Answers each call by its label: a value, an exception to raise, or a callable."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses if responses is not None else {}
        self.calls: list[dict] = []

    def run_json(self, script: str, *, label: str, timeout_s: float) -> Any:
        self.calls.append({"label": label, "timeout_s": timeout_s, "script": script})
        response = self.responses[label]
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response()
        return response


class FakeCommands:
    """Answers each command by its label: a CommandResult, an exception, or a callable(args)."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses if responses is not None else {}
        self.calls: list[dict] = []

    def run(self, args, *, label: str, timeout_s: float, env_remove=()) -> CommandResult:
        self.calls.append(
            {
                "label": label,
                "args": list(args),
                "timeout_s": timeout_s,
                "env_remove": list(env_remove),
            }
        )
        response = self.responses[label]
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(list(args))
        return response


def ok(stdout: bytes | str = b"", stderr: bytes = b"") -> CommandResult:
    """A successful command result (str stdout is encoded as UTF-8)."""
    data = stdout.encode("utf-8") if isinstance(stdout, str) else stdout
    return CommandResult(0, data, stderr)


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
    """Context with fakes. `responses` maps a label to the answer, for PowerShell and commands."""
    responses = responses if responses is not None else {}
    return Context(
        powershell=FakePowerShell(responses),
        commands=FakeCommands(responses),
        config=config if config is not None else load_default_config(),
        is_admin=is_admin,
        clock=clock or FixedClock(),
    )


def pip_probe(executable: str = "C:\\Python314\\python.exe", venv: bool = False) -> CommandResult:
    return ok(json.dumps({"executable": executable, "version": "3.14.6", "venv": venv}))


def wsl_output(text: str) -> CommandResult:
    """`wsl -l -v` output as wsl.exe prints it (UTF-16 LE, CRLF)."""
    return ok(text.replace("\n", "\r\n").encode("utf-16-le"))


def all_responses() -> dict[str, Any]:
    """Answers for every built-in check, from the samples in tests/data/."""
    return {
        "programs": sample("programs"),
        "startup": sample("startup"),
        "store_apps": sample("store_apps"),
        "scheduled_tasks": sample("scheduled_tasks"),
        "services": sample("services"),
        "pip_global:probe": pip_probe(),
        "pip_global:list": ok(json.dumps([{"name": "pip", "version": "25.2"}])),
        "wsl_distros": wsl_output((DATA / "wsl_list.txt").read_text(encoding="utf-8")),
    }
