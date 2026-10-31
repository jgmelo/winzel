"""Disk encryption of C: (BitLocker or device encryption), via Win32_EncryptableVolume.

The WMI class works on Windows 11 Home too (device encryption) and its values are
not translated, unlike the text of `manage-bde`. Requires elevation.
"""

from __future__ import annotations

from typing import Any

from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Status
from . import register
from .common import as_list

CATEGORY = "encryption"

SCRIPT = r"""
$v = Get-CimInstance -Namespace 'root/cimv2/security/microsoftvolumeencryption' `
    -ClassName Win32_EncryptableVolume -Filter "DriveLetter='C:'"
if ($v) {
    $pct = (Invoke-CimMethod -InputObject $v -MethodName GetConversionStatus).EncryptionPercentage
    ConvertTo-Json -Compress -InputObject @{
        ProtectionStatus = [int]$v.ProtectionStatus
        EncryptionPercentage = $pct
    }
}
"""

PROTECTION = {0: "desativada", 1: "ativada", 2: "desconhecida"}


class EncryptionCheck:
    id = CATEGORY
    label = "Criptografia do disco"
    area = "seguranca"
    requires_admin = True
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        rows = as_list(ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s))
        if not rows:
            return CheckResult(self.id, Status.WARN, "C: não aparece como volume criptografável")
        raw: Any = rows[0]
        protection = int(raw.get("ProtectionStatus", 2))
        pct = raw.get("EncryptionPercentage")
        text = f"C: proteção {PROTECTION.get(protection, 'desconhecida')}"
        if pct is not None:
            text += f" ({pct}% criptografado)"
        return CheckResult(self.id, Status.OK if protection == 1 else Status.WARN, text)


register(EncryptionCheck())
