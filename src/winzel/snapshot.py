"""Take a snapshot: run checks, compare inventory with the baseline, save everything."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .context import Context
from .diff import Change, diff_items
from .models import Check, CheckResult, Status, worst
from .runner import run_checks
from .status import inventory_status, inventory_summary
from .store import SnapshotInfo, Store

INVENTORY_AREA = "inventario"


@dataclass
class CheckOutcome:
    """A check's final result plus its comparison with the reference."""

    check_id: str
    label: str
    area: str
    result: CheckResult
    reference: SnapshotInfo | None = None
    comparable: bool = False
    changes: list[Change] = field(default_factory=list)

    @property
    def status(self) -> Status:
        return self.result.status

    @property
    def is_baseline(self) -> bool:
        """This snapshot is the category's baseline (nothing to compare against yet)."""
        return self.comparable and self.reference is None


@dataclass
class SnapshotReport:
    snapshot: SnapshotInfo
    outcomes: list[CheckOutcome]

    @property
    def overall_status(self) -> Status:
        return worst([o.status for o in self.outcomes])

    @property
    def changes(self) -> list[Change]:
        return [c for o in self.outcomes for c in o.changes]


OutcomeCallback = Callable[[CheckOutcome], None]


def analyse(store: Store, check: Check, result: CheckResult) -> CheckOutcome:
    """Compare an inventory result with its category baseline and set status/summary.

    A check that was skipped or failed is not compared: its items are unknown, which
    is different from "the items disappeared".
    """
    outcome = CheckOutcome(check.id, check.label, check.area, result)
    if check.area != INVENTORY_AREA or result.status.is_failure:
        return outcome
    outcome.comparable = True
    outcome.reference = store.baseline_for(check.id)
    if outcome.reference is None:
        result.status = Status.OK
        result.summary = inventory_summary([], result.summary, None)
        return outcome
    reference_items = store.items(outcome.reference.id, check.id)
    outcome.changes = diff_items(reference_items, {i.key: i for i in result.items})
    result.status = inventory_status(outcome.changes)
    result.summary = inventory_summary(
        outcome.changes, result.summary, outcome.reference.created_at
    )
    return outcome


def take_snapshot(
    store: Store,
    ctx: Context,
    checks: list[Check],
    kind: str,
    on_progress: OutcomeCallback | None = None,
) -> SnapshotReport:
    created_at = ctx.now()
    by_id = {c.id: c for c in checks}
    outcomes: dict[str, CheckOutcome] = {}

    def progress(result: CheckResult) -> None:
        outcome = analyse(store, by_id[result.check_id], result)
        outcomes[result.check_id] = outcome
        if on_progress is not None:
            on_progress(outcome)

    run_checks(checks, ctx, progress)
    ordered = [outcomes[c.id] for c in checks]
    snapshot_id = store.save_snapshot(created_at, kind, ctx.is_admin, [o.result for o in ordered])
    info = SnapshotInfo(id=snapshot_id, created_at=created_at, kind=kind, is_admin=ctx.is_admin)
    return SnapshotReport(snapshot=info, outcomes=ordered)
