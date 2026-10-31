"""Installed programs, from the registry Uninstall keys.

Sources: HKLM (64-bit), HKLM WOW6432Node (32-bit) and HKCU. Entries without
DisplayName or with SystemComponent = 1 are ignored. The key is
`normalized name|publisher`; version numbers embedded in the name are removed
so an update shows up as "changed", not "removed + added" (SPEC, risk 1).
"""

from __future__ import annotations

import re
from typing import Any

from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "programs"

SCRIPT = r"""
$uninstall = 'Microsoft\Windows\CurrentVersion\Uninstall\*'
$sources = @(
    @{ Source = 'HKLM64'; Path = "HKLM:\SOFTWARE\$uninstall" },
    @{ Source = 'HKLM32'; Path = "HKLM:\SOFTWARE\WOW6432Node\$uninstall" },
    @{ Source = 'HKCU';   Path = "HKCU:\SOFTWARE\$uninstall" }
)
$result = foreach ($s in $sources) {
    Get-ItemProperty -Path $s.Path -ErrorAction SilentlyContinue | ForEach-Object {
        [pscustomobject]@{
            Source          = $s.Source
            RegistryKey     = $_.PSChildName
            DisplayName     = $_.DisplayName
            DisplayVersion  = $_.DisplayVersion
            Publisher       = $_.Publisher
            SystemComponent = $_.SystemComponent
            InstallDate     = $_.InstallDate
        }
    }
}
ConvertTo-Json -InputObject @($result) -Depth 3 -Compress
"""

SOURCE_ORDER = {"HKLM64": 0, "HKLM32": 1, "HKCU": 2}

# Dotted version numbers, optionally prefixed by "v": 3.14.0, v2.1, 14.40.33810, 24.08
_VERSION = re.compile(r"(?<![\w.])v?\d+(?:\.\d+)+(?:[-+]?[a-z0-9]+)*(?![\w.])", re.IGNORECASE)
_EMPTY_PARENS = re.compile(r"\(\s*\)|\[\s*\]")
_SPACES = re.compile(r"\s+")
_DANGLING = " -–—,:;/"


def normalize_name(name: str) -> str:
    """'Python 3.14.0 (64-bit)' -> 'python (64-bit)'. Architecture and years are kept."""
    text = _VERSION.sub(" ", name.lower())
    text = _EMPTY_PARENS.sub(" ", text)
    text = _SPACES.sub(" ", text)
    # separators left hanging, e.g. "foo (x64) - " or "foo - (x64)"
    text = re.sub(r"\s[-–—]\s(?=\(|$)", " ", text + " ")
    text = _SPACES.sub(" ", text)
    return text.strip(_DANGLING).strip()


def normalize_publisher(publisher: str) -> str:
    return _SPACES.sub(" ", publisher.lower()).strip()


def program_key(name: str, publisher: str) -> str:
    return f"{normalize_name(name)}|{normalize_publisher(publisher)}"


def _is_system_component(value: Any) -> bool:
    try:
        return int(value) == 1
    except TypeError, ValueError:
        return False


def parse_programs(raw: Any) -> list[Item]:
    """Raw PowerShell rows -> items, filtered and de-duplicated by key."""
    rows = sorted(as_list(raw), key=lambda r: SOURCE_ORDER.get(as_text(r.get("Source")), 9))
    items: dict[str, Item] = {}
    for row in rows:
        name = as_text(row.get("DisplayName"))
        if not name or _is_system_component(row.get("SystemComponent")):
            continue
        publisher = as_text(row.get("Publisher"))
        source = as_text(row.get("Source"))
        key = program_key(name, publisher)
        if key in items:  # same program registered in more than one place
            items[key].details["sources"].append(source)
            continue
        items[key] = Item(
            category=CATEGORY,
            key=key,
            version=as_text(row.get("DisplayVersion")) or None,
            details={
                "name": name,
                "publisher": publisher,
                "sources": [source],
                "registry_key": as_text(row.get("RegistryKey")),
                "install_date": as_text(row.get("InstallDate")),
            },
        )
    return sorted(items.values(), key=lambda i: i.key)


class ProgramsCheck:
    id = CATEGORY
    label = "Programas"
    area = "inventario"
    requires_admin = False
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        raw = ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s)
        items = parse_programs(raw)
        return CheckResult(
            check_id=self.id,
            status=Status.OK,
            summary=plural(len(items), "programa", "programas"),
            items=items,
        )


register(ProgramsCheck())
