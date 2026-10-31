"""Pending Windows updates (COM Microsoft.Update.Session; slow, with its own timeout)."""

from __future__ import annotations

from typing import Any

from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Metric, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "windows_update"

SCRIPT = r"""
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$found = $searcher.Search("IsInstalled=0 and IsHidden=0")
$result = foreach ($u in $found.Updates) {
    [pscustomobject]@{
        Title    = $u.Title
        KB       = ($u.KBArticleIDs | ForEach-Object { "KB$_" }) -join ','
        Severity = $u.MsrcSeverity
        Size     = [int64]$u.MaxDownloadSize
    }
}
ConvertTo-Json -InputObject @($result) -Depth 3 -Compress
"""


def parse_pending(raw: Any) -> list[Item]:
    """One item per update. The same KB can cover several updates (e.g. one per product),
    so the key is "KB|title"; exact repetitions are listed once."""
    items: dict[str, Item] = {}
    for row in as_list(raw):
        title = as_text(row.get("Title"))
        if not title:
            continue
        kb = as_text(row.get("KB"))
        key = f"{kb}|{title}" if kb else title
        items.setdefault(
            key,
            Item(
                category=CATEGORY,
                key=key,
                version=None,
                details={"name": title, "kb": kb, "severity": as_text(row.get("Severity"))},
            ),
        )
    return list(items.values())


class WindowsUpdateCheck:
    id = CATEGORY
    label = "Windows Update"
    area = "atualizacoes"
    requires_admin = False
    timeout_s = 120.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        items = parse_pending(ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s))
        if items:
            first = items[0].details["name"]
            more = f" e mais {len(items) - 1}" if len(items) > 1 else ""
            summary = f"{plural(len(items), 'pendente', 'pendentes')}: {first}{more}"
        else:
            summary = "nenhuma atualização pendente"
        return CheckResult(
            check_id=self.id,
            status=Status.WARN if items else Status.OK,
            summary=summary,
            items=items,
            metrics=[Metric("windows_update_pending", len(items), "atualizações")],
        )


register(WindowsUpdateCheck())
