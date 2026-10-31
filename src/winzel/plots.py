"""Detailed chart with matplotlib, opened in a separate process (key `p`).

python -m winzel.plots DADOS.json   shows the chart described in the JSON file.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .timeline import Series, visible_milestones

Popen = Callable[..., object]


def payload(series: Series, milestones: list[tuple[datetime, str]]) -> dict:
    return {
        "label": series.label,
        "unit": series.unit,
        "points": [[when.isoformat(), value] for when, value in series.points],
        "milestones": [[when.isoformat(), name] for when, name in milestones],
    }


def from_payload(data: dict) -> tuple[Series, list[tuple[datetime, str]]]:
    series = Series(
        key="",
        label=data["label"],
        unit=data["unit"],
        points=[(datetime.fromisoformat(w), float(v)) for w, v in data["points"]],
    )
    milestones = [(datetime.fromisoformat(w), n) for w, n in data["milestones"]]
    return series, milestones


def figure(series: Series, milestones: list[tuple[datetime, str]], fig=None):
    """Draw the series on a matplotlib Figure (a new one by default), milestones as lines."""
    from matplotlib.dates import DateFormatter
    from matplotlib.figure import Figure

    if fig is None:
        fig = Figure(figsize=(10, 5), layout="constrained")
    ax = fig.add_subplot()
    ax.plot([w for w, _ in series.points], [v for _, v in series.points], marker="o")
    ax.set_title(series.label)
    ax.set_ylabel(series.unit)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(DateFormatter("%d/%m/%Y"))
    for when, name in visible_milestones(series, milestones):
        ax.axvline(when, color="tab:orange", linestyle="--", linewidth=1)
        ax.annotate(
            name,
            xy=(when, 1),
            xycoords=("data", "axes fraction"),
            rotation=90,
            va="top",
            ha="right",
            color="tab:orange",
        )
    fig.autofmt_xdate()
    return fig


def launch(
    series: Series,
    milestones: list[tuple[datetime, str]],
    popen: Popen = subprocess.Popen,
) -> Path:
    """Write the chart data to a temporary file and open it in another process."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="winzel-grafico-", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(payload(series, milestones), handle, ensure_ascii=False)
        path = Path(handle.name)
    popen([sys.executable, "-m", "winzel.plots", str(path)])
    return path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("uso: python -m winzel.plots DADOS.json", file=sys.stderr)
        return 2
    path = Path(args[0])
    series, milestones = from_payload(json.loads(path.read_text(encoding="utf-8")))
    path.unlink(missing_ok=True)

    import matplotlib.pyplot as plt

    window = plt.figure(figsize=(10, 5), layout="constrained")
    window.canvas.manager.set_window_title(f"winzel — {series.label}")
    figure(series, milestones, window)
    plt.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
