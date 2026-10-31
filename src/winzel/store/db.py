"""SQLite storage: schema migrations and snapshot reads/writes."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path

from ..models import CheckResult, Item, Status

_MIGRATION_NAME = re.compile(r"^(\d{4})_[\w-]+\.sql$")


def default_db_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share"
    return Path(base) / "winzel" / "winzel.db"


def migrations() -> list[tuple[int, str]]:
    """Numbered SQL migrations, in order. Numbers must be 1, 2, 3, ... without gaps."""
    found = []
    for entry in resources.files("winzel.store.migrations").iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    found.sort()
    for expected, (number, _) in enumerate(found, start=1):
        if number != expected:
            raise RuntimeError(f"migração {expected:04d} ausente")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection, target: int | None = None) -> int:
    """Apply pending migrations (up to `target`), each in its own transaction."""
    current = schema_version(conn)
    for number, sql in migrations():
        if number <= current or (target is not None and number > target):
            continue
        conn.execute("BEGIN")
        try:
            for statement in _statements(sql):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {number}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = number
    return current


def _statements(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@dataclass(frozen=True)
class SnapshotInfo:
    id: int
    created_at: datetime
    kind: str
    is_admin: bool


@dataclass(frozen=True)
class CheckRun:
    check_id: str
    status: Status
    summary: str
    duration_ms: int
    error: str | None


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @classmethod
    def open(cls, path: Path | str) -> Store:
        conn = connect(path)
        migrate(conn)
        return cls(conn)

    def close(self) -> None:
        self.conn.close()

    # --- writes -------------------------------------------------------------

    def save_snapshot(
        self, created_at: datetime, kind: str, is_admin: bool, results: list[CheckResult]
    ) -> int:
        """Write the whole snapshot in a single transaction."""
        conn = self.conn
        conn.execute("BEGIN")
        try:
            cursor = conn.execute(
                "INSERT INTO snapshots (created_at, kind, is_admin) VALUES (?, ?, ?)",
                (created_at.isoformat(timespec="seconds"), kind, int(is_admin)),
            )
            snapshot_id = cursor.lastrowid
            for r in results:
                conn.execute(
                    "INSERT INTO check_runs VALUES (?, ?, ?, ?, ?, ?)",
                    (snapshot_id, r.check_id, r.status.value, r.summary, r.duration_ms, r.error),
                )
                conn.executemany(
                    "INSERT INTO items VALUES (?, ?, ?, ?, ?)",
                    [
                        (snapshot_id, i.category, i.key, i.version, json.dumps(i.details))
                        for i in r.items
                    ],
                )
                conn.executemany(
                    "INSERT INTO metrics VALUES (?, ?, ?, ?)",
                    [(snapshot_id, m.name, m.value, m.unit) for m in r.metrics],
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return snapshot_id

    # --- reads --------------------------------------------------------------

    @staticmethod
    def _info(row: sqlite3.Row) -> SnapshotInfo:
        return SnapshotInfo(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            kind=row["kind"],
            is_admin=bool(row["is_admin"]),
        )

    def snapshot(self, snapshot_id: int) -> SnapshotInfo | None:
        row = self.conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        return self._info(row) if row else None

    def snapshots(self) -> list[SnapshotInfo]:
        rows = self.conn.execute("SELECT * FROM snapshots ORDER BY id").fetchall()
        return [self._info(r) for r in rows]

    def latest_snapshot(self) -> SnapshotInfo | None:
        row = self.conn.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        return self._info(row) if row else None

    def check_runs(self, snapshot_id: int) -> dict[str, CheckRun]:
        rows = self.conn.execute(
            "SELECT * FROM check_runs WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchall()
        return {
            r["check_id"]: CheckRun(
                check_id=r["check_id"],
                status=Status(r["status"]),
                summary=r["summary"],
                duration_ms=r["duration_ms"],
                error=r["error"],
            )
            for r in rows
        }

    def items(self, snapshot_id: int, category: str) -> dict[str, Item]:
        rows = self.conn.execute(
            "SELECT * FROM items WHERE snapshot_id = ? AND category = ? ORDER BY key",
            (snapshot_id, category),
        ).fetchall()
        return {
            r["key"]: Item(
                category=r["category"],
                key=r["key"],
                version=r["version"],
                details=json.loads(r["details_json"]),
            )
            for r in rows
        }

    def baseline_for(self, check_id: str, up_to: int | None = None) -> SnapshotInfo | None:
        """Baseline of a category: first snapshot where its check ran (not skipped/error)."""
        row = self.conn.execute(
            """
            SELECT s.* FROM snapshots s
            JOIN check_runs c ON c.snapshot_id = s.id
            WHERE c.check_id = ? AND c.status NOT IN (?, ?) AND (? IS NULL OR s.id <= ?)
            ORDER BY s.id LIMIT 1
            """,
            (check_id, Status.SKIPPED.value, Status.ERROR.value, up_to, up_to),
        ).fetchone()
        return self._info(row) if row else None
