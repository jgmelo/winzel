"""Free space on C: (psutil)."""

from __future__ import annotations

from ..config import check_option
from ..context import Context
from ..filesystem import format_gb, gb
from ..models import CheckResult, Metric
from . import register
from .common import level_below

CATEGORY = "disk_c"


class DiskCCheck:
    id = CATEGORY
    label = "Espaço livre no C:"
    area = "armazenamento"
    requires_admin = False
    timeout_s = 10.0

    def run(self, ctx: Context) -> CheckResult:
        path = check_option(ctx.config, self.id, "path", "C:\\")
        warn = float(check_option(ctx.config, self.id, "warn_below_pct", 20))
        problem = float(check_option(ctx.config, self.id, "problem_below_pct", 10))
        usage = ctx.fs.disk_usage(path)
        pct = usage.free_pct
        return CheckResult(
            check_id=self.id,
            status=level_below(pct, warn, problem),
            summary=f"{format_gb(usage.free)} livres de {format_gb(usage.total)} ({pct:.0f}%)",
            metrics=[
                Metric("disk_c_free_pct", round(pct, 2), "%"),
                Metric("disk_c_free_gb", round(gb(usage.free), 2), "GB"),
                Metric("disk_c_total_gb", round(gb(usage.total), 2), "GB"),
            ],
        )


register(DiskCCheck())
