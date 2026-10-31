"""Core data types shared by checks, storage, analysis and presentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .context import Context


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    PROBLEM = "problem"
    SKIPPED = "skipped"
    ERROR = "error"

    @property
    def emoji(self) -> str:
        return _EMOJI[self]

    @property
    def text(self) -> str:
        return _TEXT[self]

    @property
    def label(self) -> str:
        return _LABEL[self]

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    def symbol(self, use_emoji: bool = True) -> str:
        return self.emoji if use_emoji else self.text

    @property
    def is_failure(self) -> bool:
        """The check did not produce trustworthy data (skipped or error)."""
        return self in (Status.SKIPPED, Status.ERROR)


_EMOJI = {
    Status.OK: "🟢",
    Status.WARN: "🟡",
    Status.PROBLEM: "🔴",
    Status.SKIPPED: "⚪",
    Status.ERROR: "❗",
}
_TEXT = {
    Status.OK: "[OK]",
    Status.WARN: "[!]",
    Status.PROBLEM: "[X]",
    Status.SKIPPED: "[-]",
    Status.ERROR: "[ERRO]",
}
_LABEL = {
    Status.OK: "ok",
    Status.WARN: "atenção",
    Status.PROBLEM: "problema",
    Status.SKIPPED: "pulada",
    Status.ERROR: "erro",
}
_SEVERITY = {
    Status.OK: 0,
    Status.SKIPPED: 1,
    Status.WARN: 2,
    Status.ERROR: 3,
    Status.PROBLEM: 4,
}


def worst(statuses: list[Status]) -> Status:
    return max(statuses, key=lambda s: s.severity, default=Status.OK)


@dataclass
class Item:
    category: str
    key: str
    version: str | None
    details: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return str(self.details.get("name") or self.key)


@dataclass
class Metric:
    name: str
    value: float
    unit: str


@dataclass
class CheckResult:
    check_id: str
    status: Status
    summary: str
    items: list[Item] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    # Set by the analysis before `status`/`summary` are replaced by the compared ones:
    # the check's own status and summary (e.g. "6 programas").
    raw_status: Status | None = None
    raw_summary: str | None = None

    @property
    def collected(self) -> Status:
        """OK when the items were collected; SKIPPED/ERROR when they are unknown."""
        own = self.raw_status or self.status
        return own if own.is_failure else Status.OK


class Check(Protocol):
    id: str
    label: str  # Portuguese label, shown in the interface
    area: str
    requires_admin: bool
    timeout_s: float

    def run(self, ctx: Context) -> CheckResult: ...
