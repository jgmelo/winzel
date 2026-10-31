"""SQLite storage: schema migrations and snapshot reads/writes."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path

from ..models import CheckResult, Item, Status

_MIGRATION_NAME = re.compile(r"^(\d{4})_[\w-]+\.sql$")

BASELINE_MILESTONE = "linha-de-base"
BASELINE_NOTE = "Registrado automaticamente: primeiro snapshot."
APPROVABLE = ("added", "removed")


class MilestoneError(ValueError):
    """Invalid milestone operation (empty/duplicate/reserved name, unknown snapshot...)."""


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
    raw_status: Status = Status.OK
    raw_summary: str = ""


@dataclass(frozen=True)
class MilestoneInfo:
    name: str
    note: str
    created_at: datetime
    snapshot: SnapshotInfo

    @property
    def is_baseline(self) -> bool:
        return self.name == BASELINE_MILESTONE


@dataclass(frozen=True)
class Approval:
    category: str
    key: str
    change: str
    approved_at: datetime
    reason: str


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
                    """
                    INSERT INTO check_runs (snapshot_id, check_id, status, summary,
                        duration_ms, error, raw_status, raw_summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        r.check_id,
                        r.status.value,
                        r.summary,
                        r.duration_ms,
                        r.error,
                        r.collected.value,
                        r.raw_summary if r.raw_summary is not None else r.summary,
                    ),
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
            # The first snapshot becomes the `linha-de-base` milestone.
            conn.execute(
                """
                INSERT INTO milestones (snapshot_id, name, note, created_at)
                SELECT id, ?, ?, ? FROM snapshots
                WHERE id = (SELECT MIN(id) FROM snapshots)
                  AND NOT EXISTS (SELECT 1 FROM milestones WHERE name = ?)
                """,
                (
                    BASELINE_MILESTONE,
                    BASELINE_NOTE,
                    created_at.isoformat(timespec="seconds"),
                    BASELINE_MILESTONE,
                ),
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
                raw_status=Status(r["raw_status"]),
                raw_summary=r["raw_summary"],
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

    def previous_snapshot(self, snapshot_id: int) -> SnapshotInfo | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE id < ? ORDER BY id DESC LIMIT 1", (snapshot_id,)
        ).fetchone()
        return self._info(row) if row else None

    # --- references -----------------------------------------------------------
    # A category can only be compared with a snapshot where its items were collected
    # (raw_status 'ok'); a skipped or failed check says nothing about its items.

    def reference_from(
        self, check_id: str, from_id: int, up_to: int | None = None
    ) -> SnapshotInfo | None:
        """First snapshot with id >= from_id (and <= up_to) where the category was collected."""
        row = self.conn.execute(
            """
            SELECT s.* FROM snapshots s
            JOIN check_runs c ON c.snapshot_id = s.id
            WHERE c.check_id = ? AND c.raw_status = 'ok' AND s.id >= ?
              AND (? IS NULL OR s.id <= ?)
            ORDER BY s.id LIMIT 1
            """,
            (check_id, from_id, up_to, up_to),
        ).fetchone()
        return self._info(row) if row else None

    def reference_before(self, check_id: str, before_id: int | None) -> SnapshotInfo | None:
        """Last snapshot before `before_id` (or the latest) where the category was collected."""
        row = self.conn.execute(
            """
            SELECT s.* FROM snapshots s
            JOIN check_runs c ON c.snapshot_id = s.id
            WHERE c.check_id = ? AND c.raw_status = 'ok' AND (? IS NULL OR s.id < ?)
            ORDER BY s.id DESC LIMIT 1
            """,
            (check_id, before_id, before_id),
        ).fetchone()
        return self._info(row) if row else None

    def baseline_for(self, check_id: str, up_to: int | None = None) -> SnapshotInfo | None:
        """Baseline of a category: first snapshot where its items were collected."""
        return self.reference_from(check_id, 0, up_to)

    # --- milestones -----------------------------------------------------------

    def _milestone(self, row: sqlite3.Row) -> MilestoneInfo:
        snapshot = self.snapshot(row["snapshot_id"])
        assert snapshot is not None
        return MilestoneInfo(
            name=row["name"],
            note=row["note"],
            created_at=datetime.fromisoformat(row["created_at"]),
            snapshot=snapshot,
        )

    def milestones(self) -> list[MilestoneInfo]:
        """All milestones, the most recent snapshot first."""
        rows = self.conn.execute(
            "SELECT * FROM milestones ORDER BY snapshot_id DESC, created_at DESC, rowid DESC"
        ).fetchall()
        return [self._milestone(r) for r in rows]

    def milestone(self, name: str) -> MilestoneInfo | None:
        row = self.conn.execute(
            "SELECT * FROM milestones WHERE name = ? COLLATE NOCASE", (name.strip(),)
        ).fetchone()
        return self._milestone(row) if row else None

    def latest_milestone(self) -> MilestoneInfo | None:
        found = self.milestones()
        return found[0] if found else None

    def create_milestone(
        self, snapshot_id: int, name: str, note: str, created_at: datetime
    ) -> MilestoneInfo:
        name = name.strip()
        if not name:
            raise MilestoneError("o nome do milestone é obrigatório")
        if name.lower() == BASELINE_MILESTONE:
            raise MilestoneError(f"o nome {BASELINE_MILESTONE} é reservado")
        if self.snapshot(snapshot_id) is None:
            raise MilestoneError(f"snapshot #{snapshot_id} não existe")
        if self.milestone(name) is not None:
            raise MilestoneError(f"já existe um milestone chamado {name}")
        self.conn.execute(
            "INSERT INTO milestones (snapshot_id, name, note, created_at) VALUES (?, ?, ?, ?)",
            (snapshot_id, name, note.strip(), created_at.isoformat(timespec="seconds")),
        )
        created = self.milestone(name)
        assert created is not None
        return created

    def delete_milestone(self, name: str) -> None:
        found = self.milestone(name)
        if found is None:
            raise MilestoneError(f"milestone {name.strip()} não existe")
        if found.is_baseline:
            raise MilestoneError(f"o milestone {BASELINE_MILESTONE} não pode ser apagado")
        self.conn.execute("DELETE FROM milestones WHERE name = ?", (found.name,))

    # --- approvals ------------------------------------------------------------

    def approve(
        self, category: str, key: str, change: str, reason: str, approved_at: datetime
    ) -> None:
        if change not in APPROVABLE:
            raise ValueError(f"só mudanças {APPROVABLE} podem ser aprovadas, não {change!r}")
        self.conn.execute(
            "INSERT OR REPLACE INTO approvals VALUES (?, ?, ?, ?, ?)",
            (category, key, change, approved_at.isoformat(timespec="seconds"), reason.strip()),
        )

    def revoke(self, category: str, key: str, change: str) -> None:
        self.conn.execute(
            "DELETE FROM approvals WHERE category = ? AND key = ? AND change = ?",
            (category, key, change),
        )

    def approvals(self) -> dict[tuple[str, str, str], Approval]:
        rows = self.conn.execute("SELECT * FROM approvals").fetchall()
        return {
            (r["category"], r["key"], r["change"]): Approval(
                category=r["category"],
                key=r["key"],
                change=r["change"],
                approved_at=datetime.fromisoformat(r["approved_at"]),
                reason=r["reason"],
            )
            for r in rows
        }

    # --- retention (SPEC 6.3) ---------------------------------------------------

    def protected_snapshots(self) -> set[int]:
        """Milestone snapshots plus the effective reference of each category of each milestone."""
        protected: set[int] = set()
        check_ids = [r[0] for r in self.conn.execute("SELECT DISTINCT check_id FROM check_runs")]
        for milestone in self.milestones():
            protected.add(milestone.snapshot.id)
            for check_id in check_ids:
                ref = self.reference_from(check_id, milestone.snapshot.id)
                if ref is not None:
                    protected.add(ref.id)
        return protected

    def apply_retention(self, now: datetime, keep_all_days: int = 90) -> list[int]:
        """Automatic snapshots older than `keep_all_days` are reduced to the last one per month.

        Manual snapshots and protected snapshots (see `protected_snapshots`) are kept.
        Returns the ids that were deleted.
        """
        limit = (now - timedelta(days=keep_all_days)).isoformat(timespec="seconds")
        old = self.conn.execute(
            "SELECT id, created_at FROM snapshots WHERE kind = 'auto' AND created_at < ?"
            " ORDER BY id",
            (limit,),
        ).fetchall()
        last_of_month: dict[str, int] = {}
        for row in old:
            last_of_month[row["created_at"][:7]] = row["id"]
        keep = set(last_of_month.values()) | self.protected_snapshots()
        doomed = [row["id"] for row in old if row["id"] not in keep]
        if doomed:
            self.conn.executemany("DELETE FROM snapshots WHERE id = ?", [(i,) for i in doomed])
        return doomed
