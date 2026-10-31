"""Runs external commands (pip, wsl) that do not go through PowerShell."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CommandResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


class CommandError(Exception):
    pass


class CommandNotFound(CommandError):
    """The executable does not exist on this machine."""


class CommandTimeout(CommandError):
    pass


class CommandRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        label: str,
        timeout_s: float,
        env_remove: Sequence[str] = (),
    ) -> CommandResult: ...


def first_line(data: bytes, encoding: str = "utf-8") -> str:
    text = data.decode(encoding, errors="replace").replace("\x00", "").strip()
    return text.splitlines()[0].strip() if text else ""


class Commands:
    """Production runner. `run` is injectable so command handling can be tested."""

    def __init__(self, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self._run = run

    def run(
        self,
        args: Sequence[str],
        *,
        label: str,
        timeout_s: float,
        env_remove: Sequence[str] = (),
    ) -> CommandResult:
        env = {k: v for k, v in os.environ.items() if k not in set(env_remove)}
        try:
            completed = self._run(
                list(args),
                capture_output=True,
                timeout=timeout_s,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise CommandNotFound(f"{label}: comando não encontrado ({args[0]})") from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandTimeout(f"{label}: tempo esgotado ({timeout_s:g} s)") from exc
        except OSError as exc:
            raise CommandError(f"{label}: não foi possível executar {args[0]} ({exc})") from exc
        return CommandResult(completed.returncode, completed.stdout or b"", completed.stderr or b"")
