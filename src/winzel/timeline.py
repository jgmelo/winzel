"""Time line: one series per inventory category (item count) and per metric."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import Check
from .store import Store

INVENTORY_AREA = "inventario"
DEFAULT_SERIES = "metric:disk_c_free_pct"

METRIC_LABELS = {
    "disk_c_free_pct": "Espaço livre no C: (%)",
    "disk_c_free_gb": "Espaço livre no C: (GB)",
    "dev_drive_free_pct": "Espaço livre no Dev Drive (%)",
    "dev_drive_free_gb": "Espaço livre no Dev Drive (GB)",
    "dev_drive_vhdx_gb": "Tamanho do VHDX do Dev Drive (GB)",
    "clutter_total_gb": "Sandboxes + Temp (GB)",
    "clutter_sandboxes_gb": "Sandboxes (GB)",
    "clutter_temp_gb": "Temp (GB)",
    "battery_health_pct": "Saúde da bateria (%)",
    "battery_cycles": "Ciclos da bateria",
    "ssd_wear_pct": "Desgaste do SSD (%)",
    "ssd_temperature_c": "Temperatura do SSD (°C)",
}
HIDDEN_METRICS = {"disk_c_total_gb", "dev_drive_total_gb", "battery_full_mwh", "battery_design_mwh"}


@dataclass
class Series:
    key: str
    label: str
    unit: str
    points: list[tuple[datetime, float]] = field(default_factory=list)


@dataclass
class Timeline:
    series: list[Series]
    milestones: list[tuple[datetime, str]]

    def get(self, key: str) -> Series | None:
        return next((s for s in self.series if s.key == key), None)

    def default_key(self) -> str | None:
        if self.get(DEFAULT_SERIES):
            return DEFAULT_SERIES
        return self.series[0].key if self.series else None


def build_timeline(store: Store, checks: list[Check]) -> Timeline:
    when = {s.id: s.created_at for s in store.snapshots()}
    series: dict[str, Series] = {}

    for snapshot_id, name, value, unit in store.metric_values():
        if name in HIDDEN_METRICS:
            continue
        key = f"metric:{name}"
        if key not in series:
            series[key] = Series(key, METRIC_LABELS.get(name, name), unit)
        series[key].points.append((when[snapshot_id], value))

    inventory = {c.id: c.label for c in checks if c.area == INVENTORY_AREA}
    counts = [row for row in store.item_counts() if row[1] in inventory]
    for check_id, label in inventory.items():
        points = [(when[sid], float(n)) for sid, cid, n in counts if cid == check_id]
        if points:
            series[f"count:{check_id}"] = Series(
                f"count:{check_id}", f"{label} (quantidade)", "itens", points
            )

    metric_order = list(METRIC_LABELS)
    ordered = sorted(
        series.values(),
        key=lambda s: (
            0 if s.key.startswith("metric:") else 1,
            metric_order.index(s.key[7:]) if s.key[7:] in metric_order else len(metric_order),
        ),
    )
    milestones = sorted((m.snapshot.created_at, m.name) for m in store.milestones())
    return Timeline(series=ordered, milestones=milestones)


def visible_milestones(
    series: Series, milestones: list[tuple[datetime, str]]
) -> list[tuple[datetime, str]]:
    """Milestones inside the time span of the series."""
    if not series.points:
        return []
    first, last = series.points[0][0], series.points[-1][0]
    return [(when, name) for when, name in milestones if first <= when <= last]


def days_since(start: datetime, moment: datetime) -> float:
    return (moment - start).total_seconds() / 86400


def draw_terminal_plot(plt, series: Series, milestones: list[tuple[datetime, str]]) -> None:
    """Draw on a plotext object: the series plus milestones as labelled vertical lines."""
    plt.clear_figure()
    plt.title(series.label)
    if not series.points:
        return
    start = series.points[0][0]
    xs = [days_since(start, when) for when, _ in series.points]
    ys = [value for _, value in series.points]
    plt.plot(xs, ys, marker="braille")
    top = max(ys)
    for when, name in visible_milestones(series, milestones):
        x = days_since(start, when)
        plt.vline(x, "orange")
        plt.text(name, x, top, color="orange", alignment="left")
    step = max(1, len(xs) // 6)
    ticks = xs[::step]
    labels = [when.strftime("%d/%m") for when, _ in series.points[::step]]
    plt.xticks(ticks, labels)
    plt.ylabel(series.unit)
