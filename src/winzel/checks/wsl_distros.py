"""WSL distributions, from `wsl -l -v`.

wsl.exe prints UTF-16 LE (SPEC, risk 3) and translates the table headers, so
the output is decoded specially and parsed by column position, not by header.
The live state (Running/Stopped) and the default distro are not compared.
"""

from __future__ import annotations

from ..commands import CommandNotFound, first_line
from ..config import check_timeout
from ..context import Context
from ..models import CheckResult, Item, Status
from . import register
from .common import plural

CATEGORY = "wsl_distros"
COMMAND = ["wsl.exe", "--list", "--verbose"]

# Messages (and error codes) meaning "WSL works, but there are no distros".
NO_DISTROS = (
    "wsl_e_default_distro_not_found",
    "has no installed distributions",
    "não tem distribuições instaladas",
    "não possui distribuições instaladas",
)


class WslError(Exception):
    pass


def decode_wsl(data: bytes) -> str:
    """UTF-16 LE (with or without BOM) when it looks like it; UTF-8 otherwise."""
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    if len(data) >= 2 and data[1:2] == b"\x00":
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def parse_wsl_list(text: str) -> list[Item]:
    """Lines after the header: [*] NAME STATE VERSION."""
    lines = [line.strip() for line in text.replace("\x00", "").splitlines() if line.strip()]
    items = []
    for line in lines[1:]:
        default = line.startswith("*")
        parts = line.lstrip("*").split()
        if len(parts) < 3:
            continue
        name, state, version = " ".join(parts[:-2]), parts[-2], parts[-1]
        items.append(
            Item(
                category=CATEGORY,
                key=name.lower(),
                version=version,
                details={"name": name, "state": state, "default": default},
            )
        )
    return sorted(items, key=lambda i: i.key)


def means_no_distros(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in NO_DISTROS)


class WslDistrosCheck:
    id = CATEGORY
    label = "Distribuições WSL"
    area = "inventario"
    requires_admin = False
    timeout_s = 20.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        try:
            result = ctx.commands.run(COMMAND, label=self.id, timeout_s=timeout_s)
        except CommandNotFound:
            return CheckResult(self.id, Status.OK, "WSL não instalado (0 distribuições)")
        output = decode_wsl(result.stdout) + "\n" + decode_wsl(result.stderr)
        if result.returncode != 0:
            if means_no_distros(output):
                return CheckResult(self.id, Status.OK, "nenhuma distribuição instalada")
            reason = first_line(output.encode("utf-8")) or f"código {result.returncode}"
            raise WslError(f"wsl falhou: {reason}")
        items = parse_wsl_list(decode_wsl(result.stdout))
        return CheckResult(
            check_id=self.id,
            status=Status.OK,
            summary=plural(len(items), "distribuição", "distribuições"),
            items=items,
        )


register(WslDistrosCheck())
