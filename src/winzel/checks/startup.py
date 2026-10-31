"""Startup entries: Run/RunOnce keys and Startup folders, with on/off state.

The on/off state comes from `...\\Explorer\\StartupApproved`: the first byte of
the value is odd when the entry is disabled (02 = on, 03 = off). Entries without
a StartupApproved value, and RunOnce entries, are on.
"""

from __future__ import annotations

from typing import Any

from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "startup"

SCRIPT = r"""
$cv = 'Microsoft\Windows\CurrentVersion'
$runKeys = @(
    @{ Location = 'hkcu_run';       Path = "HKCU:\Software\$cv\Run" },
    @{ Location = 'hkcu_runonce';   Path = "HKCU:\Software\$cv\RunOnce" },
    @{ Location = 'hklm_run';       Path = "HKLM:\SOFTWARE\$cv\Run" },
    @{ Location = 'hklm_runonce';   Path = "HKLM:\SOFTWARE\$cv\RunOnce" },
    @{ Location = 'hklm32_run';     Path = "HKLM:\SOFTWARE\WOW6432Node\$cv\Run" },
    @{ Location = 'hklm32_runonce'; Path = "HKLM:\SOFTWARE\WOW6432Node\$cv\RunOnce" }
)
$entries = New-Object System.Collections.ArrayList
foreach ($k in $runKeys) {
    $key = Get-Item -Path $k.Path -ErrorAction SilentlyContinue
    if (-not $key) { continue }
    foreach ($name in $key.GetValueNames()) {
        if ($name -eq '') { continue }
        [void]$entries.Add([pscustomobject]@{
            Location = $k.Location; Name = $name; Command = [string]$key.GetValue($name)
        })
    }
}
$shell = New-Object -ComObject WScript.Shell
$folders = @(
    @{ Location = 'startup_user';   Path = [Environment]::GetFolderPath('Startup') },
    @{ Location = 'startup_common'; Path = [Environment]::GetFolderPath('CommonStartup') }
)
foreach ($f in $folders) {
    if (-not $f.Path -or -not (Test-Path -LiteralPath $f.Path)) { continue }
    Get-ChildItem -LiteralPath $f.Path -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne 'desktop.ini' } | ForEach-Object {
            $command = $_.FullName
            if ($_.Extension -eq '.lnk') {
                try {
                    $lnk = $shell.CreateShortcut($_.FullName)
                    $command = ($lnk.TargetPath + ' ' + $lnk.Arguments).Trim()
                } catch { }
            }
            [void]$entries.Add([pscustomobject]@{
                Location = $f.Location; Name = $_.Name; Command = $command
            })
        }
}
$approvedRoot = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'
$approvedKeys = @(
    @{ Hive = 'HKCU'; List = 'Run';           Path = "HKCU:\$approvedRoot\Run" },
    @{ Hive = 'HKCU'; List = 'Run32';         Path = "HKCU:\$approvedRoot\Run32" },
    @{ Hive = 'HKCU'; List = 'StartupFolder'; Path = "HKCU:\$approvedRoot\StartupFolder" },
    @{ Hive = 'HKLM'; List = 'Run';           Path = "HKLM:\$approvedRoot\Run" },
    @{ Hive = 'HKLM'; List = 'Run32';         Path = "HKLM:\$approvedRoot\Run32" },
    @{ Hive = 'HKLM'; List = 'StartupFolder'; Path = "HKLM:\$approvedRoot\StartupFolder" }
)
$approved = New-Object System.Collections.ArrayList
foreach ($a in $approvedKeys) {
    $key = Get-Item -Path $a.Path -ErrorAction SilentlyContinue
    if (-not $key) { continue }
    foreach ($name in $key.GetValueNames()) {
        $bytes = $key.GetValue($name)
        if ($bytes -is [byte[]] -and $bytes.Length -gt 0) {
            [void]$approved.Add([pscustomobject]@{
                Hive = $a.Hive; List = $a.List; Name = $name; Flag = [int]$bytes[0]
            })
        }
    }
}
ConvertTo-Json -InputObject @{ entries = @($entries); approved = @($approved) } -Depth 4 -Compress
"""

LOCATIONS = {
    "hkcu_run": "HKCU Run",
    "hkcu_runonce": "HKCU RunOnce",
    "hklm_run": "HKLM Run",
    "hklm_runonce": "HKLM RunOnce",
    "hklm32_run": "HKLM Run (32 bits)",
    "hklm32_runonce": "HKLM RunOnce (32 bits)",
    "startup_user": "Pasta Inicializar (usuário)",
    "startup_common": "Pasta Inicializar (todos os usuários)",
}

# Location -> (hive, list) in StartupApproved. RunOnce has no on/off state.
APPROVED_LIST = {
    "hkcu_run": ("HKCU", "Run"),
    "hklm_run": ("HKLM", "Run"),
    "hklm32_run": ("HKLM", "Run32"),
    "startup_user": ("HKCU", "StartupFolder"),
    "startup_common": ("HKLM", "StartupFolder"),
}

ON = "ligado"
OFF = "desligado"


def is_disabled(flag: int) -> bool:
    return flag % 2 == 1


def parse_startup(raw: Any) -> list[Item]:
    raw = raw or {}
    approved: dict[tuple[str, str, str], int] = {}
    for row in as_list(raw.get("approved")):
        hive, lst, name = (
            as_text(row.get("Hive")),
            as_text(row.get("List")),
            as_text(row.get("Name")),
        )
        try:
            approved[(hive, lst, name.lower())] = int(row.get("Flag"))
        except TypeError, ValueError:
            continue

    items: dict[str, Item] = {}
    for row in as_list(raw.get("entries")):
        location = as_text(row.get("Location"))
        name = as_text(row.get("Name"))
        if not name:
            continue
        command = as_text(row.get("Command"))
        enabled = True
        if location in APPROVED_LIST:
            hive, lst = APPROVED_LIST[location]
            flag = approved.get((hive, lst, name.lower()))
            enabled = flag is None or not is_disabled(flag)
        state = ON if enabled else OFF
        key = f"{name.lower()}|{location}"
        items[key] = Item(
            category=CATEGORY,
            key=key,
            version=f"{state}: {command}",
            details={
                "name": name,
                "location": location,
                "location_label": LOCATIONS.get(location, location),
                "command": command,
                "enabled": enabled,
            },
        )
    return sorted(items.values(), key=lambda i: i.key)


def summarize(items: list[Item]) -> str:
    off = sum(1 for i in items if not i.details["enabled"])
    text = plural(len(items), "item", "itens")
    return f"{text} ({off} desligado{'s' if off != 1 else ''})" if off else text


class StartupCheck:
    id = CATEGORY
    label = "Inicialização"
    area = "inventario"
    requires_admin = False
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        raw = ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s)
        items = parse_startup(raw)
        return CheckResult(
            check_id=self.id, status=Status.OK, summary=summarize(items), items=items
        )


register(StartupCheck())
