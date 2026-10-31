"""Third-party scheduled tasks (outside \\Microsoft\\).

The comparable attribute is the actions plus enabled/disabled. The live state
(Ready/Running/Queued) is left out: it changes on its own and would show up as
"changed" for no reason.

Without elevation Windows hides some tasks, so this category is only compared
with a baseline taken with the same elevation (`same_elevation_only`).
"""

from __future__ import annotations

from typing import Any

from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Status
from . import register
from .common import as_list, as_text, plural

CATEGORY = "scheduled_tasks"

SCRIPT = r"""
$result = Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\Microsoft\*' } |
    ForEach-Object {
        [pscustomobject]@{
            TaskPath = $_.TaskPath
            TaskName = $_.TaskName
            State    = [string]$_.State
            Actions  = @($_.Actions | ForEach-Object {
                [pscustomobject]@{
                    Execute   = $_.Execute
                    Arguments = $_.Arguments
                    ClassId   = $_.ClassId
                }
            })
        }
    }
ConvertTo-Json -InputObject @($result) -Depth 4 -Compress
"""

ENABLED = "habilitada"
DISABLED = "desabilitada"


def is_microsoft(task_path: str) -> bool:
    return task_path.lower().startswith("\\microsoft\\")


def describe_action(action: dict) -> str:
    execute = as_text(action.get("Execute"))
    if execute:
        return f"{execute} {as_text(action.get('Arguments'))}".strip()
    class_id = as_text(action.get("ClassId"))
    return f"COM {class_id}" if class_id else "?"


def parse_scheduled_tasks(raw: Any) -> list[Item]:
    items: dict[str, Item] = {}
    for row in as_list(raw):
        path = as_text(row.get("TaskPath")) or "\\"
        name = as_text(row.get("TaskName"))
        if not name or is_microsoft(path):
            continue
        enabled = as_text(row.get("State")).lower() != "disabled"
        actions = "; ".join(describe_action(a) for a in as_list(row.get("Actions")))
        key = f"{path}|{name}"
        items[key] = Item(
            category=CATEGORY,
            key=key,
            version=f"{ENABLED if enabled else DISABLED}: {actions}",
            details={
                "name": f"{path}{name}",
                "path": path,
                "task": name,
                "actions": actions,
                "enabled": enabled,
                "state": as_text(row.get("State")),
            },
        )
    return sorted(items.values(), key=lambda i: i.key.lower())


def summarize(items: list[Item]) -> str:
    off = sum(1 for i in items if not i.details["enabled"])
    text = plural(len(items), "tarefa", "tarefas")
    return f"{text} ({off} desabilitada{'s' if off != 1 else ''})" if off else text


class ScheduledTasksCheck:
    id = CATEGORY
    label = "Tarefas agendadas"
    area = "inventario"
    requires_admin = False
    same_elevation_only = True
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        raw = ctx.powershell.run_json(SCRIPT, label=self.id, timeout_s=timeout_s)
        items = parse_scheduled_tasks(raw)
        return CheckResult(
            check_id=self.id, status=Status.OK, summary=summarize(items), items=items
        )


register(ScheduledTasksCheck())
