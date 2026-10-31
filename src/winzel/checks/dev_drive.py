"""Dev Drive: free space on its drive letter and size of the VHDX file behind it.

The VHDX path comes from `checks.dev_drive.vhdx` or, when empty, is discovered by
asking Windows which virtual disk file backs the drive letter.
"""

from __future__ import annotations

from ..config import check_option
from ..context import Context
from ..filesystem import format_gb, gb
from ..models import CheckResult, Metric, Status
from . import register
from .common import as_list, as_text, level_below

CATEGORY = "dev_drive"

DISCOVER = r"""
$letter = '{letter}'
$disk = Get-Partition -DriveLetter $letter -ErrorAction SilentlyContinue |
    Get-Disk -ErrorAction SilentlyContinue
if ($disk) {{
    $info = @{{ Location = $disk.Location; BusType = [string]$disk.BusType }}
    ConvertTo-Json -InputObject $info -Compress
}}
"""


def discover_vhdx(raw) -> str:
    """Location of a file-backed disk ending in .vhdx/.vhd, or ""."""
    for row in as_list(raw):
        location = as_text(row.get("Location"))
        if location.lower().endswith((".vhdx", ".vhd")):
            return location
    return ""


class DevDriveCheck:
    id = CATEGORY
    label = "Dev Drive"
    area = "armazenamento"
    requires_admin = False
    timeout_s = 20.0

    def run(self, ctx: Context) -> CheckResult:
        letter = str(check_option(ctx.config, self.id, "letter", "D:")).rstrip("\\").upper()
        warn = float(check_option(ctx.config, self.id, "warn_below_pct", 20))
        try:
            usage = ctx.fs.disk_usage(letter + "\\")
        except FileNotFoundError:
            return CheckResult(
                self.id, Status.SKIPPED, f"indisponível: unidade {letter} não encontrada"
            )
        pct = usage.free_pct
        metrics = [
            Metric("dev_drive_free_pct", round(pct, 2), "%"),
            Metric("dev_drive_free_gb", round(gb(usage.free), 2), "GB"),
            Metric("dev_drive_total_gb", round(gb(usage.total), 2), "GB"),
        ]
        summary = (
            f"{letter} {format_gb(usage.free)} livres de {format_gb(usage.total)} ({pct:.0f}%)"
        )

        vhdx = as_text(check_option(ctx.config, self.id, "vhdx", ""))
        if not vhdx:
            try:
                script = DISCOVER.format(letter=letter.rstrip(":"))
                vhdx = discover_vhdx(ctx.powershell.run_json(script, label=self.id, timeout_s=15))
            except Exception:  # discovery is best effort; free space still counts
                vhdx = ""
        try:
            size = ctx.fs.file_size(vhdx) if vhdx else None
        except FileNotFoundError:
            size = None
        if size is None:
            summary += " · VHDX não encontrado (defina checks.dev_drive.vhdx)"
        else:
            metrics.append(Metric("dev_drive_vhdx_gb", round(gb(size), 2), "GB"))
            summary += f" · VHDX {format_gb(size)}"
        return CheckResult(self.id, level_below(pct, warn), summary, metrics=metrics)


register(DevDriveCheck())
