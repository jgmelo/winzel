"""Age of the latest system restore point (Get-ComputerRestorePoint; requires elevation)."""

from __future__ import annotations

from datetime import datetime

from ..config import check_option, check_timeout
from ..context import Context
from ..models import CheckResult, Metric, Status
from . import register
from .common import as_list, as_text

CATEGORY = "restore_point"

SCRIPT = r"""
$result = Get-ComputerRestorePoint | ForEach-Object {
    [pscustomobject]@{
        Created     = ([Management.ManagementDateTimeConverter]::ToDateTime(
            $_.CreationTime)).ToString('s')
        Description = $_.Description
    }
}
ConvertTo-Json -InputObject @($result) -Compress
"""


class RestorePointCheck:
    id = CATEGORY
    label = "Ponto de restauração"
    area = "backup"
    requires_admin = True
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        max_days = float(check_option(ctx.config, self.id, "warn_after_days", 30))
        points = [
            (datetime.fromisoformat(as_text(p.get("Created"))), as_text(p.get("Description")))
            for p in as_list(ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s))
            if as_text(p.get("Created"))
        ]
        if not points:
            return CheckResult(self.id, Status.WARN, "nenhum ponto de restauração")
        created, description = max(points)
        age_days = (ctx.now() - created).total_seconds() / 86400
        summary = f"último em {created.strftime('%d/%m/%Y')} ({age_days:.0f} dias): {description}"
        return CheckResult(
            self.id,
            Status.WARN if age_days > max_days else Status.OK,
            summary,
            metrics=[Metric("restore_point_age_days", round(age_days, 2), "dias")],
        )


register(RestorePointCheck())
