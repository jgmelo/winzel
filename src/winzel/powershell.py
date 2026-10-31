"""Runs Windows PowerShell 5.1 scripts and parses their JSON output.

Scripts are sent with -EncodedCommand (no quoting issues) and output is forced
to UTF-8. Each script is expected to print a single JSON document.
"""

from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Callable
from typing import Any, Protocol

PREAMBLE = (
    "$ErrorActionPreference = 'Stop'; "
    "$ProgressPreference = 'SilentlyContinue'; "
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$OutputEncoding = [System.Text.Encoding]::UTF8;\n"
)


class PowerShellError(Exception):
    pass


class PowerShellTimeout(PowerShellError):
    pass


class PowerShellRunner(Protocol):
    def run_json(self, script: str, *, label: str, timeout_s: float) -> Any: ...


def build_command(script: str, executable: str = "powershell.exe") -> list[str]:
    encoded = base64.b64encode((PREAMBLE + script).encode("utf-16-le")).decode("ascii")
    return [
        executable,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


def parse_output(stdout: bytes, label: str) -> Any:
    text = stdout.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise PowerShellError(f"{label}: saída do PowerShell não é JSON válido ({exc})") from exc


class PowerShell:
    """Production runner. `run` is injectable so command handling can be tested."""

    def __init__(
        self,
        executable: str = "powershell.exe",
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.executable = executable
        self._run = run

    def run_json(self, script: str, *, label: str, timeout_s: float) -> Any:
        command = build_command(script, self.executable)
        try:
            completed = self._run(
                command,
                capture_output=True,
                timeout=timeout_s,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise PowerShellTimeout(f"{label}: tempo esgotado ({timeout_s:g} s)") from exc
        except OSError as exc:
            raise PowerShellError(
                f"{label}: não foi possível executar o PowerShell ({exc})"
            ) from exc
        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
            first = stderr.splitlines()[0] if stderr else f"código {completed.returncode}"
            raise PowerShellError(f"{label}: PowerShell falhou — {first}")
        return parse_output(completed.stdout or b"", label)
