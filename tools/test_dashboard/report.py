"""Pure functions that turn test records into dashboard structures and history."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .model import PASSED, FileGroup, FunctionGroup, RunMeta, TestRecord, Totals
from .taxonomy import AREAS, PHASES, area_order, phase_order

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


def group_by_file(records: list[TestRecord]) -> list[FileGroup]:
    """Files in alphabetical order; inside each, functions in source order with their cases."""
    files: dict[str, dict[str, FunctionGroup]] = {}
    for record in records:
        functions = files.setdefault(record.file, {})
        group = functions.setdefault(record.function, FunctionGroup(record.file, record.function))
        group.cases.append(record)
    return [
        FileGroup(file, sorted(functions.values(), key=lambda f: (f.line, f.function)))
        for file, functions in sorted(files.items())
    ]


@dataclass
class MatrixCell:
    cases: int = 0
    functions: int = 0


def area_columns() -> list[str]:
    """All areas of the SPEC, so empty columns show areas no test exercises yet."""
    return list(AREAS)


def file_area_matrix(files: list[FileGroup]) -> dict[str, dict[str, MatrixCell]]:
    """{file: {area: cases and functions}} for the overview heat map."""
    matrix: dict[str, dict[str, MatrixCell]] = {}
    for group in files:
        row = matrix.setdefault(group.file, {})
        for function in group.functions:
            cell = row.setdefault(function.area, MatrixCell())
            cell.cases += len(function.cases)
            cell.functions += 1
    return matrix


def phase_summary(records: list[TestRecord]) -> dict[str, Totals]:
    """Totals per phase, in SPEC order (phases without tests are left out)."""
    by_phase: dict[str, list[TestRecord]] = {}
    for record in records:
        by_phase.setdefault(record.phase, []).append(record)
    order = sorted(by_phase, key=lambda p: (phase_order(p), p))
    return {phase: Totals.of(by_phase[phase]) for phase in order}


def known_phases() -> list[str]:
    return list(PHASES)


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
