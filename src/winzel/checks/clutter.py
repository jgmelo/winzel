"""Clutter: size of the sandbox folders and of the user's Temp folder.

The limit applies to the sum; each folder is shown separately in the summary.
A folder that does not exist counts as 0 GB.
"""

from __future__ import annotations

from ..config import check_option
from ..context import Context
from ..filesystem import format_number, gb
from ..models import CheckResult, Metric
from . import register
from .common import level_above

CATEGORY = "clutter"


def folder_list(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in value or []]


class ClutterCheck:
    id = CATEGORY
    label = "Sandboxes e Temp"
    area = "armazenamento"
    requires_admin = False
    timeout_s = 60.0

    def run(self, ctx: Context) -> CheckResult:
        groups = {
            "sandboxes": folder_list(
                check_option(ctx.config, self.id, "sandboxes", ["C:\\Sandbox"])
            ),
            "temp": folder_list(check_option(ctx.config, self.id, "temp", "%TEMP%")),
        }
        labels = {"sandboxes": "sandboxes", "temp": "Temp"}
        warn_above = float(check_option(ctx.config, self.id, "warn_above_gb", 5))
        sizes: dict[str, float] = {}
        notes: list[str] = []
        for group, folders in groups.items():
            total = 0
            for folder in folders:
                path = ctx.fs.expand(folder)
                try:
                    size = ctx.fs.dir_size(path)
                except FileNotFoundError:
                    notes.append(f"{path} não existe")
                    continue
                total += size.bytes
                if size.unreadable:
                    notes.append(f"{size.unreadable} itens inacessíveis em {path}")
            sizes[group] = gb(total)
        total_gb = sum(sizes.values())
        parts = ", ".join(f"{labels[g]} {format_number(v)} GB" for g, v in sizes.items())
        summary = f"{format_number(total_gb)} GB no total — {parts}"
        if notes:
            summary += f" ({'; '.join(notes)})"
        metrics = [Metric(f"clutter_{g}_gb", round(v, 3), "GB") for g, v in sizes.items()]
        metrics.append(Metric("clutter_total_gb", round(total_gb, 3), "GB"))
        return CheckResult(self.id, level_above(total_gb, warn_above), summary, metrics=metrics)


register(ClutterCheck())
