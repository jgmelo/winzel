"""SSD wear and temperature (Get-StorageReliabilityCounter; requires elevation).

Virtual disks (e.g. the Dev Drive VHDX) and disks without data are ignored.
With several SSDs, the metrics record the worst wear and the highest temperature.
"""

from __future__ import annotations

from typing import Any

from ..config import check_option, check_timeout
from ..context import Context
from ..models import CheckResult, Metric, Status
from . import register
from .common import as_list, as_text, level_above

CATEGORY = "ssd"

SCRIPT = r"""
$result = Get-PhysicalDisk | ForEach-Object {
    $counter = $_ | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
    [pscustomobject]@{
        FriendlyName = $_.FriendlyName
        MediaType    = [string]$_.MediaType
        BusType      = [string]$_.BusType
        Wear         = $counter.Wear
        Temperature  = $counter.Temperature
    }
}
ConvertTo-Json -InputObject @($result) -Depth 3 -Compress
"""


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except TypeError, ValueError:
        return None


def parse_disks(raw: Any) -> list[dict]:
    disks = []
    for row in as_list(raw):
        bus = as_text(row.get("BusType")).lower()
        media = as_text(row.get("MediaType")).lower()
        if "virtual" in bus or bus in ("file backed virtual", "usb"):
            continue
        if media != "ssd" and bus != "nvme":
            continue
        disks.append(
            {
                "name": as_text(row.get("FriendlyName")) or "?",
                "wear": _number(row.get("Wear")),
                "temperature": _number(row.get("Temperature")),
            }
        )
    return disks


def describe(disk: dict) -> str:
    parts = []
    if disk["wear"] is not None:
        parts.append(f"desgaste {disk['wear']:.0f}%")
    if disk["temperature"] is not None:
        parts.append(f"{disk['temperature']:.0f} °C")
    return f"{disk['name']}: {', '.join(parts) or 'sem dados'}"


class SsdCheck:
    id = CATEGORY
    label = "SSD"
    area = "hardware"
    requires_admin = True
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        warn_above = float(check_option(ctx.config, self.id, "warn_above_wear_pct", 50))
        disks = parse_disks(ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s))
        wears = [d["wear"] for d in disks if d["wear"] is not None]
        temps = [d["temperature"] for d in disks if d["temperature"] is not None]
        if not wears and not temps:
            return CheckResult(self.id, Status.SKIPPED, "indisponível: sem dados de SSD")
        metrics = []
        status = Status.OK
        if wears:
            metrics.append(Metric("ssd_wear_pct", max(wears), "%"))
            status = level_above(max(wears), warn_above)
        if temps:
            metrics.append(Metric("ssd_temperature_c", max(temps), "°C"))
        summary = "; ".join(describe(d) for d in disks)
        if not wears:
            summary += " (desgaste indisponível)"
        return CheckResult(self.id, status, summary, metrics=metrics)


register(SsdCheck())
