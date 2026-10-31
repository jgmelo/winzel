"""Microsoft Defender: protection on and age of the signatures (Get-MpComputerStatus)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..config import check_option, check_timeout
from ..context import Context
from ..models import CheckResult, Metric, Status
from . import register
from .common import as_text

CATEGORY = "defender"

SCRIPT = r"""
$s = Get-MpComputerStatus
ConvertTo-Json -Compress -InputObject @{
    AntivirusEnabled          = [bool]$s.AntivirusEnabled
    RealTimeProtectionEnabled = [bool]$s.RealTimeProtectionEnabled
    SignatureLastUpdated      = $s.AntivirusSignatureLastUpdated.ToString('s')
    SignatureVersion          = $s.AntivirusSignatureVersion
}
"""


class DefenderCheck:
    id = CATEGORY
    label = "Microsoft Defender"
    area = "seguranca"
    requires_admin = False
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        max_days = float(check_option(ctx.config, self.id, "warn_signature_days", 3))
        raw: Any = ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s) or {}
        off = [
            label
            for key, label in (
                ("AntivirusEnabled", "antivírus"),
                ("RealTimeProtectionEnabled", "proteção em tempo real"),
            )
            if raw.get(key) is not True
        ]
        updated = datetime.fromisoformat(as_text(raw.get("SignatureLastUpdated")))
        age_days = (ctx.now() - updated).total_seconds() / 86400
        metrics = [Metric("defender_signature_age_days", round(age_days, 2), "dias")]
        age_text = f"assinaturas de {updated.strftime('%d/%m/%Y')} ({age_days:.0f} dias)"
        if off:
            return CheckResult(
                self.id,
                Status.PROBLEM,
                f"desligado: {', '.join(off)} · {age_text}",
                metrics=metrics,
            )
        status = Status.WARN if age_days > max_days else Status.OK
        return CheckResult(self.id, status, f"proteção ativa · {age_text}", metrics=metrics)


register(DefenderCheck())
