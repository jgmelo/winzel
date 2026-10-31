"""Store apps (AppX/MSIX) of the current user, without frameworks or system apps."""

from __future__ import annotations

from typing import Any

from ..config import check_option, check_timeout
from ..context import Context
from ..models import CheckResult, Item, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "store_apps"

SCRIPT = r"""
$result = Get-AppxPackage | ForEach-Object {
    [pscustomobject]@{
        Name              = $_.Name
        Version           = [string]$_.Version
        Publisher         = $_.Publisher
        Architecture      = [string]$_.Architecture
        PackageFamilyName = $_.PackageFamilyName
        IsFramework       = [bool]$_.IsFramework
        IsResourcePackage = [bool]$_.IsResourcePackage
        SignatureKind     = [string]$_.SignatureKind
        NonRemovable      = [bool]$_.NonRemovable
    }
}
ConvertTo-Json -InputObject @($result) -Depth 3 -Compress
"""


def _flag(value: Any) -> bool:
    return value is True or as_text(value).lower() == "true"


def is_user_app(row: dict) -> bool:
    """Frameworks, resource packages and System-signed apps are left out."""
    if _flag(row.get("IsFramework")) or _flag(row.get("IsResourcePackage")):
        return False
    return as_text(row.get("SignatureKind")).lower() != "system"


def parse_store_apps(raw: Any, ignore: list[str] | tuple[str, ...] = ()) -> list[Item]:
    """`ignore`: package names left out (case-insensitive), e.g. Microsoft.Winget.Source."""
    ignored = {n.lower() for n in ignore}
    items: dict[str, Item] = {}
    for row in as_list(raw):
        name = as_text(row.get("Name"))
        if not name or not is_user_app(row) or name.lower() in ignored:
            continue
        arch = as_text(row.get("Architecture"))
        if name in items:  # same package installed for more than one architecture
            items[name].details["architectures"].append(arch)
            continue
        items[name] = Item(
            category=CATEGORY,
            key=name,
            version=as_text(row.get("Version")) or None,
            details={
                "name": name,
                "publisher": as_text(row.get("Publisher")),
                "architectures": [arch],
                "family": as_text(row.get("PackageFamilyName")),
                "signature": as_text(row.get("SignatureKind")),
            },
        )
    return sorted(items.values(), key=lambda i: i.key.lower())


class StoreAppsCheck:
    id = CATEGORY
    label = "Apps da Store"
    area = "inventario"
    requires_admin = False
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        raw = ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s)
        items = parse_store_apps(raw, check_option(ctx.config, self.id, "ignore", []))
        return CheckResult(
            check_id=self.id,
            status=Status.OK,
            summary=plural(len(items), "app", "apps"),
            items=items,
        )


register(StoreAppsCheck())
