"""Packages in the global Python, which should hold nothing but pip (SPEC, seção 3).

winzel itself runs inside a venv, so the global interpreter is found explicitly:
`checks.pip_global.python` in config.toml, or else the `py -3.14` launcher with
VIRTUAL_ENV removed from the environment. Before listing packages, the same
interpreter reports its path and whether it is a venv; a venv is an error.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..commands import CommandError, CommandNotFound, CommandResult, first_line
from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "pip_global"
DEFAULT_LAUNCHER = ["py", "-3.14"]
ALLOWED = {"pip"}

PROBE = (
    "import json, sys; print(json.dumps({'executable': sys.executable, "
    "'version': sys.version.split()[0], 'venv': sys.prefix != sys.base_prefix}))"
)


class Unavailable(Exception):
    """The global Python could not be found or started."""


def interpreter(config: dict) -> list[str]:
    """`python` in config: a path, or a list (e.g. ["py", "-3.13"]); default `py -3.14`."""
    configured = config.get("checks", {}).get(CATEGORY, {}).get("python")
    if isinstance(configured, list) and configured:
        return [str(part) for part in configured]
    if as_text(configured):
        return [as_text(configured)]
    return list(DEFAULT_LAUNCHER)


def normalize_package(name: str) -> str:
    """PEP 503: 'Typing_Extensions' -> 'typing-extensions'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_probe(result: CommandResult) -> dict:
    if result.returncode != 0:
        reason = first_line(result.stderr) or first_line(result.stdout)
        raise Unavailable(reason or f"código {result.returncode}")
    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise Unavailable(f"resposta inesperada do Python ({exc})") from exc
    return data


def parse_pip_list(raw: Any) -> list[Item]:
    items = {}
    for row in as_list(raw):
        name = as_text(row.get("name"))
        if not name:
            continue
        key = normalize_package(name)
        items[key] = Item(
            category=CATEGORY,
            key=key,
            version=as_text(row.get("version")) or None,
            details={"name": name},
        )
    return sorted(items.values(), key=lambda i: i.key)


def status_rule(items: list[Item]) -> Status:
    """🟡 while the global Python holds anything besides pip."""
    return Status.WARN if any(i.key not in ALLOWED for i in items) else Status.OK


def summarize(items: list[Item], executable: str) -> str:
    extras = sum(1 for i in items if i.key not in ALLOWED)
    count = plural(len(items), "pacote", "pacotes")
    detail = f"{extras} além do pip" if extras else "só o pip"
    return f"{count} ({detail}) em {executable}"


class PipGlobalCheck:
    id = CATEGORY
    label = "Python global (pip)"
    area = "inventario"
    requires_admin = False
    timeout_s = 30.0

    def status_rule(self, items: list[Item]) -> Status:
        return status_rule(items)

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        python = interpreter(ctx.config)

        def call(*args: str, label: str) -> CommandResult:
            return ctx.commands.run(
                [*python, *args], label=label, timeout_s=timeout_s, env_remove=["VIRTUAL_ENV"]
            )

        try:
            info = parse_probe(call("-c", PROBE, label=f"{self.id}:probe"))
        except (CommandNotFound, Unavailable) as exc:
            return CheckResult(
                check_id=self.id,
                status=Status.SKIPPED,
                summary=f"indisponível: Python global não encontrado ({exc})",
            )
        executable = as_text(info.get("executable"))
        if info.get("venv"):
            raise CommandError(f"o Python indicado é um venv ({executable})")

        listing = call(
            "-m",
            "pip",
            "list",
            "--format=json",
            "--disable-pip-version-check",
            label=f"{self.id}:list",
        )
        if listing.returncode != 0:
            reason = first_line(listing.stderr) or f"código {listing.returncode}"
            raise CommandError(f"pip list falhou: {reason}")
        try:
            raw = json.loads(listing.stdout.decode("utf-8", errors="replace") or "[]")
        except ValueError as exc:
            raise CommandError(f"saída do pip não é JSON válido ({exc})") from exc
        items = parse_pip_list(raw)
        for item in items:
            item.details["python"] = executable
        return CheckResult(
            check_id=self.id,
            status=status_rule(items),
            summary=summarize(items, executable),
            items=items,
        )


register(PipGlobalCheck())
