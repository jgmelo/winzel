"""Packages with updates available in winget (module Microsoft.WinGet.Client)."""

from __future__ import annotations

from typing import Any

from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Metric, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "winget_updates"
MODULE = "Microsoft.WinGet.Client"

SCRIPT = r"""
if (-not (Get-Module -ListAvailable -Name Microsoft.WinGet.Client)) {
    ConvertTo-Json -InputObject @{ module_missing = $true } -Compress
    return
}
Import-Module Microsoft.WinGet.Client
$result = Get-WinGetPackage | Where-Object { $_.IsUpdateAvailable } | ForEach-Object {
    [pscustomobject]@{
        Id        = $_.Id
        Name      = $_.Name
        Installed = [string]$_.InstalledVersion
        Available = [string]($_.AvailableVersions | Select-Object -First 1)
        Source    = $_.Source
    }
}
ConvertTo-Json -InputObject @{ packages = @($result) } -Depth 3 -Compress
"""

SHOWN_IN_SUMMARY = 3


class ModuleMissing(Exception):
    pass


def parse_updates(raw: Any) -> list[Item]:
    raw = raw or {}
    if raw.get("module_missing"):
        raise ModuleMissing(MODULE)
    items = []
    for row in as_list(raw.get("packages")):
        package_id = as_text(row.get("Id"))
        if not package_id:
            continue
        installed, available = as_text(row.get("Installed")), as_text(row.get("Available"))
        items.append(
            Item(
                category=CATEGORY,
                key=package_id,
                version=f"{installed} → {available}",
                details={
                    "name": as_text(row.get("Name")) or package_id,
                    "installed": installed,
                    "available": available,
                    "source": as_text(row.get("Source")),
                },
            )
        )
    return sorted(items, key=lambda i: i.details["name"].lower())


def summarize(items: list[Item]) -> str:
    if not items:
        return "nenhuma atualização pendente"
    shown = ", ".join(f"{i.details['name']} ({i.version})" for i in items[:SHOWN_IN_SUMMARY])
    more = f" e mais {len(items) - SHOWN_IN_SUMMARY}" if len(items) > SHOWN_IN_SUMMARY else ""
    return f"{plural(len(items), 'atualização', 'atualizações')}: {shown}{more}"


class WingetUpdatesCheck:
    id = CATEGORY
    label = "Atualizações do winget"
    area = "atualizacoes"
    requires_admin = False
    timeout_s = 60.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        try:
            items = parse_updates(
                ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s)
            )
        except ModuleMissing:
            return CheckResult(
                self.id,
                Status.SKIPPED,
                f"indisponível: módulo {MODULE} não instalado "
                f"(Install-Module {MODULE} -Scope CurrentUser)",
            )
        return CheckResult(
            check_id=self.id,
            status=Status.WARN if items else Status.OK,
            summary=summarize(items),
            items=items,
            metrics=[Metric("winget_updates_count", len(items), "pacotes")],
        )


register(WingetUpdatesCheck())
