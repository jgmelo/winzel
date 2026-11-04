"""Data structures for the test dashboard, independent of pytest.

A *case* is one collected test (a parametrized function yields several cases);
a *function* is one `def test_…`; functions are grouped by test file.
"""

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
    """Result of one test case, with everything the dashboard shows about it."""

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
    file: str = ""
    function: str = ""
    params: str = ""
    line: int = 0
    file_doc: str = ""

    def __post_init__(self) -> None:
        path, _, rest = self.nodeid.partition("::")
        if not self.file:
            self.file = path
        if not self.function:
            base = rest.split("::")[-1] if rest else self.nodeid
            self.function, _, params = base.partition("[")
            if not self.params:
                self.params = params.rstrip("]")


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
class FunctionGroup:
    """One test function and its cases (one case unless parametrized)."""

    file: str
    function: str
    cases: list[TestRecord] = field(default_factory=list)

    @property
    def first(self) -> TestRecord:
        return self.cases[0]

    @property
    def name(self) -> str:
        return self.first.name.split(" [")[0]

    @property
    def docstring(self) -> str:
        return self.first.docstring

    @property
    def phase(self) -> str:
        return self.first.phase

    @property
    def area(self) -> str:
        return self.first.area

    @property
    def line(self) -> int:
        return self.first.line

    @property
    def source(self) -> str:
        return self.first.source

    @property
    def parametrized(self) -> bool:
        return len(self.cases) > 1 or bool(self.first.params)

    @property
    def totals(self) -> Totals:
        return Totals.of(self.cases)

    @property
    def outcome(self) -> str:
        """Failed if any case failed; skipped if all were skipped; passed otherwise."""
        totals = self.totals
        if totals.failed:
            return FAILED
        if totals.skipped == totals.total:
            return SKIPPED
        return PASSED

    @property
    def duration_s(self) -> float:
        return sum(c.duration_s for c in self.cases)


@dataclass
class FileGroup:
    """One test file (a topic of the dashboard) and its functions."""

    file: str
    functions: list[FunctionGroup] = field(default_factory=list)

    @property
    def topic(self) -> str:
        stem = self.file.rsplit("/", 1)[-1].removesuffix(".py")
        return stem.removeprefix("test_")

    @property
    def anchor(self) -> str:
        return f"arquivo-{self.topic}"

    @property
    def lead(self) -> str:
        return self.functions[0].first.file_doc if self.functions else ""

    @property
    def cases(self) -> list[TestRecord]:
        return [c for f in self.functions for c in f.cases]

    @property
    def totals(self) -> Totals:
        return Totals.of(self.cases)
