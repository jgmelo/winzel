"""Data structures for the test dashboard, independent of pytest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"

ICONS = {PASSED: "✅", FAILED: "❌", SKIPPED: "⏭️"}
OUTCOME_LABELS = {PASSED: "aprovado", FAILED: "falhou", SKIPPED: "pulado"}


@dataclass
class TestRecord:
    """Result of one test, with everything the dashboard shows about it."""

    __test__ = False  # not a pytest test class

    nodeid: str
    name: str
    docstring: str
    phase: str
    area: str
    outcome: str
    duration_s: float = 0.0
    message: str = ""
    source: str = ""


@dataclass
class RunMeta:
    """Context of a test run, shown in the dashboard header."""

    generated_at: datetime
    duration_s: float
    parent_hash: str | None = None
    parent_message: str | None = None
    branch: str | None = None


@dataclass
class Totals:
    passed: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped

    def add(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)

    @classmethod
    def of(cls, records: list[TestRecord]) -> Totals:
        totals = cls()
        for record in records:
            totals.add(record.outcome)
        return totals


@dataclass
class AreaGroup:
    area: str
    records: list[TestRecord] = field(default_factory=list)

    @property
    def totals(self) -> Totals:
        return Totals.of(self.records)


@dataclass
class PhaseGroup:
    phase: str
    areas: list[AreaGroup] = field(default_factory=list)

    @property
    def totals(self) -> Totals:
        return Totals.of([r for group in self.areas for r in group.records])
