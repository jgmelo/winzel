"""Closed list of actions (Ações tab), always in two steps:

1. `plan(ctx, report)` only reads: it describes exactly what would be done
   (commands, packages, folders) or why there is nothing to do;
2. `execute(ctx, plan)` changes the system, and is only called after the user
   confirms that plan explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .commands import CommandNotFound, first_line
from .config import check_option
from .context import Context
from .filesystem import format_gb
from .snapshot import SnapshotReport

RESTORE_POINT_SCRIPT = r"""
Checkpoint-Computer -Description 'winzel' -RestorePointType MODIFY_SETTINGS
ConvertTo-Json -InputObject @{ ok = $true } -Compress
"""


@dataclass
class Plan:
    """What an action would do. `commands` are run as-is by `execute`."""

    action_id: str
    title: str
    steps: list[str] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    nothing_to_do: str | None = None
    note: str = ""

    @property
    def details(self) -> str:
        lines = [f"• {s}" for s in self.steps]
        if self.note:
            lines += ["", self.note]
        return "\n".join(lines)


@dataclass
class ActionResult:
    ok: bool
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _run_all(ctx: Context, plan: Plan, label: str, timeout_s: float) -> ActionResult:
    lines, ok = [], True
    for command, target in zip(plan.commands, plan.targets, strict=True):
        try:
            result = ctx.commands.run(command, label=label, timeout_s=timeout_s)
        except CommandNotFound:
            return ActionResult(False, [f"{command[0]} não encontrado"])
        if result.returncode == 0:
            lines.append(f"✔ {target}")
        else:
            ok = False
            reason = first_line(result.stderr) or first_line(result.stdout)
            lines.append(f"✖ {target}: {reason or f'código {result.returncode}'}")
    return ActionResult(ok, lines)


class WingetUpgradeAction:
    id = "winget_upgrade"
    label = "Atualizar pacotes do winget"
    description = "Atualiza, um a um, os pacotes que o último snapshot listou com atualização."
    requires_admin = False

    def plan(self, ctx: Context, report: SnapshotReport | None) -> Plan:
        outcome = next(
            (o for o in (report.outcomes if report else []) if o.check_id == "winget_updates"),
            None,
        )
        items = outcome.result.items if outcome else []
        plan = Plan(self.id, "Atualizar estes pacotes com o winget?")
        if not items:
            plan.nothing_to_do = "Nenhum pacote do winget com atualização no snapshot exibido."
            return plan
        for item in items:
            plan.steps.append(f"{item.details['name']} ({item.key}): {item.version}")
            plan.commands.append(
                [
                    "winget",
                    "upgrade",
                    "--id",
                    item.key,
                    "--exact",
                    "--silent",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ]
            )
            plan.targets.append(item.details["name"])
        plan.note = "Comando: winget upgrade --id <pacote> --exact --silent"
        return plan

    def execute(self, ctx: Context, plan: Plan) -> ActionResult:
        return _run_all(ctx, plan, self.id, timeout_s=900)


class EmptyTempAction:
    id = "empty_temp"
    label = "Esvaziar a pasta Temp"
    description = "Apaga o conteúdo do %TEMP% do usuário; arquivos em uso são ignorados."
    requires_admin = False

    def _path(self, ctx: Context) -> str:
        return ctx.fs.expand(str(check_option(ctx.config, "clutter", "temp", "%TEMP%")))

    def plan(self, ctx: Context, report: SnapshotReport | None) -> Plan:
        path = self._path(ctx)
        plan = Plan(self.id, "Apagar o conteúdo da pasta Temp?", targets=[path])
        try:
            size = ctx.fs.dir_size(path)
        except FileNotFoundError:
            plan.nothing_to_do = f"{path} não existe."
            return plan
        if size.files == 0:
            plan.nothing_to_do = f"{path} já está vazia."
            return plan
        plan.steps.append(f"Apagar {size.files} arquivos ({format_gb(size.bytes)}) de {path}")
        plan.note = "Arquivos em uso por outros programas são ignorados."
        return plan

    def execute(self, ctx: Context, plan: Plan) -> ActionResult:
        (path,) = plan.targets
        result = ctx.fs.clear_dir(path)
        lines = [f"✔ {result.removed} itens apagados de {path}"]
        if result.failed:
            lines.append(f"• {result.failed} itens em uso foram mantidos")
        return ActionResult(True, lines)


class EmptySandboxesAction:
    id = "empty_sandboxes"
    label = "Esvaziar as sandboxes"
    description = "Pede ao Sandboxie-Plus que esvazie cada caixa (delete_sandbox_silent)."
    requires_admin = False

    def plan(self, ctx: Context, report: SnapshotReport | None) -> Plan:
        options = ctx.config.get("actions", {}).get("sandboxie", {})
        start = ctx.fs.expand(str(options.get("start_exe", "")))
        boxes_dir = ctx.fs.expand(str(options.get("boxes_dir", "")))
        plan = Plan(self.id, "Esvaziar estas caixas do Sandboxie?")
        if not start or not ctx.fs.exists(start):
            plan.nothing_to_do = f"Sandboxie-Plus não encontrado ({start or 'não configurado'})."
            return plan
        try:
            boxes = ctx.fs.list_dirs(boxes_dir)
        except FileNotFoundError:
            plan.nothing_to_do = f"Nenhuma caixa: {boxes_dir} não existe."
            return plan
        if not boxes:
            plan.nothing_to_do = f"Nenhuma caixa em {boxes_dir}."
            return plan
        for box in boxes:
            plan.steps.append(f"Caixa {box} ({boxes_dir}\\{box})")
            plan.commands.append([start, f"/box:{box}", "delete_sandbox_silent"])
            plan.targets.append(box)
        plan.note = (
            f'Comando: "{start}" /box:<caixa> delete_sandbox_silent — '
            "o Sandboxie não esvazia caixas com programas abertos."
        )
        return plan

    def execute(self, ctx: Context, plan: Plan) -> ActionResult:
        return _run_all(ctx, plan, self.id, timeout_s=120)


class RestorePointAction:
    id = "restore_point"
    label = "Criar ponto de restauração"
    description = "Cria um ponto de restauração do sistema (requer administrador)."
    requires_admin = True

    def plan(self, ctx: Context, report: SnapshotReport | None) -> Plan:
        return Plan(
            self.id,
            "Criar um ponto de restauração agora?",
            steps=["Checkpoint-Computer -Description 'winzel' -RestorePointType MODIFY_SETTINGS"],
            note="O Windows cria no máximo um ponto a cada 24 horas; os demais são ignorados.",
        )

    def execute(self, ctx: Context, plan: Plan) -> ActionResult:
        ctx.powershell.run_json(RESTORE_POINT_SCRIPT, label=self.id, timeout_s=300)
        return ActionResult(True, ["✔ ponto de restauração solicitado ao Windows"])


class MilestoneAction:
    """Same as the `m` key: the milestone dialog is its own confirmation."""

    id = "milestone"
    label = "Criar milestone"
    description = "Fixa o snapshot exibido como milestone (o mesmo que a tecla m)."
    requires_admin = False


ACTIONS = [
    WingetUpgradeAction(),
    EmptyTempAction(),
    EmptySandboxesAction(),
    RestorePointAction(),
    MilestoneAction(),
]


def get_action(action_id: str):
    return next(a for a in ACTIONS if a.id == action_id)
