"""Pure functions that turn test records into dashboard structures and history."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .model import PASSED, AreaGroup, PhaseGroup, RunMeta, TestRecord, Totals
from .taxonomy import area_order, phase_order

MAX_MESSAGE_CHARS = 200
HISTORY_SCHEMA = 1


def readable_name(test_name: str) -> str:
    """`test_programa_novo[x]` -> `programa novo [x]`."""
    base, bracket, params = test_name.partition("[")
    base = base.removeprefix("test_").replace("_", " ").strip()
    return f"{base} [{params}" if bracket else base


def summarize_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    """Reduce a failure or skip message to its first meaningful line, truncated."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    first = lines[0].removeprefix("E ").strip()
    first = first.removeprefix("Skipped: ")
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first


def group_records(records: list[TestRecord]) -> list[PhaseGroup]:
    """Group records by phase, then by area, in taxonomy order."""
    by_phase: dict[str, dict[str, list[TestRecord]]] = {}
    for record in records:
        by_phase.setdefault(record.phase, {}).setdefault(record.area, []).append(record)
    groups = []
    for phase in sorted(by_phase, key=lambda p: (phase_order(p), p)):
        areas = by_phase[phase]
        groups.append(
            PhaseGroup(
                phase=phase,
                areas=[
                    AreaGroup(area=area, records=areas[area])
                    for area in sorted(areas, key=lambda a: (area_order(a), a))
                ],
            )
        )
    return groups


def capabilities(records: list[TestRecord]) -> dict[str, list[str]]:
    """Docstrings of passing tests, by area: what winzel can do today."""
    result: dict[str, list[str]] = {}
    for record in sorted(records, key=lambda r: area_order(r.area)):
        if record.outcome != PASSED or not record.docstring:
            continue
        sentence = record.docstring.strip().splitlines()[0].strip()
        bucket = result.setdefault(record.area, [])
        if sentence not in bucket:
            bucket.append(sentence)
    return result


# --- history ------------------------------------------------------------------


def history_entry(records: list[TestRecord], meta: RunMeta) -> dict:
    """Summary of one run, saved as one JSON per commit."""
    totals = Totals.of(records)
    return {
        "schema": HISTORY_SCHEMA,
        "generated_at": meta.generated_at.isoformat(timespec="seconds"),
        "parent_hash": meta.parent_hash,
        "parent_message": meta.parent_message,
        "branch": meta.branch,
        "duration_s": round(meta.duration_s, 3),
        "totals": {
            "passed": totals.passed,
            "failed": totals.failed,
            "skipped": totals.skipped,
            "total": totals.total,
        },
        "by_phase": dict(sorted(Counter(r.phase for r in records).items())),
        "by_area": dict(sorted(Counter(r.area for r in records).items())),
    }


def history_filename(entry: dict) -> str:
    """Sortable name: timestamp + short hash of the parent commit."""
    stamp = entry["generated_at"].replace("-", "").replace(":", "")[:15]
    parent = (entry.get("parent_hash") or "inicial")[:7]
    return f"{stamp}_{parent}.json"


def write_history_entry(directory: Path, entry: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / history_filename(entry)
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_history(directory: Path) -> list[dict]:
    """All history entries, oldest first. Unreadable files are ignored."""
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if isinstance(entry, dict) and entry.get("schema") == HISTORY_SCHEMA:
            entries.append(entry)
    return entries
