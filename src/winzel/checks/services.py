"""Third-party services: Win32_Service whose executable is outside C:\\Windows.

The comparable attribute is the start mode plus the executable path (without
arguments). The live state (running/stopped) is left out.
"""

from __future__ import annotations

import re
from typing import Any

from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "services"
WINDOWS_DIR = "C:\\Windows"

SCRIPT = r"""
$result = Get-CimInstance -ClassName Win32_Service | ForEach-Object {
    [pscustomobject]@{
        Name             = $_.Name
        DisplayName      = $_.DisplayName
        PathName         = $_.PathName
        StartMode        = $_.StartMode
        DelayedAutoStart = $_.DelayedAutoStart
        State            = $_.State
    }
}
ConvertTo-Json -InputObject @($result) -Depth 3 -Compress
"""

START_MODES = {
    "auto": "automático",
    "manual": "manual",
    "disabled": "desativado",
    "boot": "boot",
    "system": "sistema",
}
DELAYED = "automático (atrasado)"

_ENV = re.compile(r"%(systemroot|windir)%", re.IGNORECASE)


def executable_path(path_name: str) -> str:
    """Executable of a service command line, without quotes or arguments.

    'C:\\Program Files\\X\\svc.exe -k' -> 'C:\\Program Files\\X\\svc.exe'
    '%SystemRoot%\\system32\\svchost.exe -k netsvcs' -> 'C:\\Windows\\system32\\svchost.exe'
    """
    text = path_name.strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        text = text[1:end] if end > 0 else text[1:]
    else:
        # Unquoted: cut after ".exe"; without ".exe" the arguments cannot be told
        # apart from spaces in the path, so the whole command line is kept.
        match = re.search(r"\.exe(?=\s|$)", text, re.IGNORECASE)
        text = text[: match.end()] if match else text
    text = _ENV.sub(lambda _: WINDOWS_DIR, text)
    if text.lower().startswith("\\systemroot\\"):
        text = WINDOWS_DIR + text[len("\\SystemRoot") :]
    return text.removeprefix("\\??\\")


def is_windows_path(path: str) -> bool:
    return path.lower().startswith(WINDOWS_DIR.lower() + "\\")


def start_mode(row: dict) -> str:
    mode = as_text(row.get("StartMode")).lower()
    if mode == "auto" and row.get("DelayedAutoStart") is True:
        return DELAYED
    return START_MODES.get(mode, mode or "?")


def parse_services(raw: Any) -> list[Item]:
    items: dict[str, Item] = {}
    for row in as_list(raw):
        name = as_text(row.get("Name"))
        path_name = as_text(row.get("PathName"))
        if not name or not path_name:
            continue
        exe = executable_path(path_name)
        if is_windows_path(exe):
            continue
        mode = start_mode(row)
        items[name.lower()] = Item(
            category=CATEGORY,
            key=name.lower(),
            version=f"{mode}: {exe}",
            details={
                "name": as_text(row.get("DisplayName")) or name,
                "service": name,
                "executable": exe,
                "command": path_name,
                "start_mode": mode,
                "state": as_text(row.get("State")),
            },
        )
    return sorted(items.values(), key=lambda i: i.key)


class ServicesCheck:
    id = CATEGORY
    label = "Serviços"
    area = "inventario"
    requires_admin = False
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        raw = ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s)
        items = parse_services(raw)
        return CheckResult(
            check_id=self.id,
            status=Status.OK,
            summary=plural(len(items), "serviço", "serviços"),
            items=items,
        )


register(ServicesCheck())
