"""Battery health: full charge capacity vs. design capacity (powercfg battery report)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..commands import first_line
from ..config import check_option, check_timeout
from ..context import Context
from ..filesystem import format_number
from ..models import CheckResult, Metric, Status
from . import register
from .common import level_below

CATEGORY = "battery"
REPORT_NAME = "winzel-battery-report.xml"


class BatteryError(Exception):
    pass


def parse_battery_report(xml_text: str) -> list[dict]:
    """One dict per battery: design, full (mWh) and cycles (or None)."""
    try:
        root = ET.fromstring(xml_text.lstrip("\ufeff"))
    except ET.ParseError as exc:
        raise BatteryError(f"relatório de bateria ilegível ({exc})") from exc
    batteries = []
    for battery in root.iterfind(".//{*}Batteries/{*}Battery"):

        def number(tag: str, battery=battery) -> float | None:
            text = battery.findtext(f"{{*}}{tag}")
            try:
                return float(text) if text not in (None, "") else None
            except ValueError:
                return None

        design, full = number("DesignCapacity"), number("FullChargeCapacity")
        if design and full is not None:
            batteries.append({"design": design, "full": full, "cycles": number("CycleCount")})
    return batteries


class BatteryCheck:
    id = CATEGORY
    label = "Bateria"
    area = "hardware"
    requires_admin = False
    timeout_s = 30.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        warn = float(check_option(ctx.config, self.id, "warn_below_pct", 80))
        problem = float(check_option(ctx.config, self.id, "problem_below_pct", 60))
        path = ctx.fs.temp_path(REPORT_NAME)
        result = ctx.commands.run(
            ["powercfg", "/batteryreport", "/xml", "/output", path],
            label=self.id,
            timeout_s=timeout_s,
        )
        if result.returncode != 0:
            reason = first_line(result.stderr) or first_line(result.stdout)
            raise BatteryError(f"powercfg falhou: {reason or f'código {result.returncode}'}")
        try:
            batteries = parse_battery_report(ctx.fs.read_text(path))
        finally:
            ctx.fs.remove(path)
        if not batteries:
            return CheckResult(self.id, Status.SKIPPED, "indisponível: nenhuma bateria encontrada")
        design = sum(b["design"] for b in batteries)
        full = sum(b["full"] for b in batteries)
        health = 100.0 * full / design
        metrics = [
            Metric("battery_health_pct", round(health, 2), "%"),
            Metric("battery_full_mwh", full, "mWh"),
            Metric("battery_design_mwh", design, "mWh"),
        ]
        summary = (
            f"{health:.0f}% da capacidade de projeto "
            f"({format_number(full / 1000)} de {format_number(design / 1000)} Wh)"
        )
        cycles = [b["cycles"] for b in batteries if b["cycles"] is not None]
        if cycles:
            metrics.append(Metric("battery_cycles", sum(cycles), "ciclos"))
            summary += f" · {int(sum(cycles))} ciclos"
        return CheckResult(self.id, level_below(health, warn, problem), summary, metrics=metrics)


register(BatteryCheck())
