"""Take a snapshot, and compare a snapshot's inventory with a reference.

The same analysis runs when a snapshot is taken (against the default reference)
and when the interface switches the reference of a snapshot already stored.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .context import Context
from .diff import Change, apply_approvals, diff_items
from .models import Check, CheckResult, Item, Status, worst
from .reference import Reference, default_reference
from .runner import run_checks
from .status import inventory_status, inventory_summary
from .store import SnapshotInfo, Store

INVENTORY_AREA = "inventario"
DEFAULT_KEEP_ALL_DAYS = 90


@dataclass
class CheckOutcome:
    """A check's result after comparison with the reference."""

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
        """This snapshot is the category's reference itself (nothing to compare yet)."""
        return self.comparable and self.reference is None

    @property
    def pending(self) -> list[Change]:
        return [c for c in self.changes if c.affects_status]


@dataclass
class SnapshotReport:
    snapshot: SnapshotInfo
    outcomes: list[CheckOutcome]
    reference: Reference | None = None
    pruned: list[int] = field(default_factory=list)

    @property
    def overall_status(self) -> Status:
        return worst([o.status for o in self.outcomes])

    @property
    def changes(self) -> list[Change]:
        return [c for o in self.outcomes for c in o.changes]

    @property
    def reference_label(self) -> str:
        return self.reference.label if self.reference else "linha de base"


OutcomeCallback = Callable[[CheckOutcome], None]


def own_status(check: Check, items: list[Item]) -> Status:
    """A check may add its own rule (e.g. pip_global: 🟡 with any package besides pip)."""
    rule = getattr(check, "status_rule", None)
    return rule(items) if rule is not None else Status.OK


def elevation_text(is_admin: bool) -> str:
    return "com admin" if is_admin else "sem admin"


def analyse(
    store: Store,
    check: Check,
    result: CheckResult,
    is_admin: bool,
    reference: Reference | None = None,
    current_id: int | None = None,
    approvals: dict | None = None,
) -> CheckOutcome:
    """Compare an inventory result with its reference and set the final status/summary.

    The check's own status and summary are kept in `raw_status`/`raw_summary`.
    A check that was skipped or failed is not compared: its items are unknown, which
    is different from "the items disappeared". A check marked `same_elevation_only`
    is not compared with a reference taken with a different elevation (⚪).
    """
    if result.raw_status is None:
        result.raw_status, result.raw_summary = result.status, result.summary
    base = result.raw_summary or ""
    outcome = CheckOutcome(check.id, check.label, check.area, result)
    if check.area != INVENTORY_AREA or result.collected.is_failure:
        return outcome

    effective = reference.resolve(store, check.id, current_id) if reference else None
    if (
        effective is not None
        and getattr(check, "same_elevation_only", False)
        and effective.is_admin != is_admin
    ):
        outcome.reference = effective
        result.status = Status.SKIPPED
        what = (
            "linha de base"
            if reference is not None and reference.milestone and reference.milestone.is_baseline
            else "referência"
        )
        result.summary = (
            f"{base} — não comparada: {what} feita "
            f"{elevation_text(effective.is_admin)}, este snapshot {elevation_text(is_admin)}"
        )
        return outcome

    outcome.comparable = True
    outcome.reference = effective
    extra = own_status(check, result.items)
    if effective is None:
        result.status = extra
        if reference is None:
            result.summary = f"{base} — linha de base registrada agora"
        elif reference.milestone is None:
            result.summary = f"{base} — sem snapshot anterior para comparar"
        else:
            result.summary = f"{base} — primeira leitura válida desde {reference.label}"
        return outcome

    if effective.id == current_id:
        changes: list[Change] = []
    else:
        reference_items = store.items(effective.id, check.id)
        changes = diff_items(reference_items, {i.key: i for i in result.items})
    outcome.changes = apply_approvals(changes, approvals or {})
    result.status = worst([inventory_status(outcome.changes), extra])
    result.summary = inventory_summary(outcome.changes, base, reference.since(effective))
    return outcome


def take_snapshot(
    store: Store,
    ctx: Context,
    checks: list[Check],
    kind: str,
    on_progress: OutcomeCallback | None = None,
    reference: Reference | None = None,
) -> SnapshotReport:
    """Run the checks, compare with `reference` (default: latest milestone) and save."""
    created_at = ctx.now()
    reference = reference or default_reference(store)
    approvals = store.approvals()
    by_id = {c.id: c for c in checks}
    outcomes: dict[str, CheckOutcome] = {}

    def progress(result: CheckResult) -> None:
        check = by_id[result.check_id]
        outcome = analyse(store, check, result, ctx.is_admin, reference, None, approvals)
        outcomes[result.check_id] = outcome
        if on_progress is not None:
            on_progress(outcome)

    run_checks(checks, ctx, progress)
    ordered = [outcomes[c.id] for c in checks]
    snapshot_id = store.save_snapshot(created_at, kind, ctx.is_admin, [o.result for o in ordered])
    info = SnapshotInfo(id=snapshot_id, created_at=created_at, kind=kind, is_admin=ctx.is_admin)
    keep_days = int(ctx.config.get("retention", {}).get("keep_all_days", DEFAULT_KEEP_ALL_DAYS))
    pruned = store.apply_retention(created_at, keep_days)
    return SnapshotReport(snapshot=info, outcomes=ordered, reference=reference, pruned=pruned)


def compare_snapshot(
    store: Store,
    checks: list[Check],
    snapshot: SnapshotInfo,
    reference: Reference | None,
) -> SnapshotReport:
    """Compare a stored snapshot with another reference, without running the checks."""
    runs = store.check_runs(snapshot.id)
    approvals = store.approvals()
    outcomes = []
    for check in checks:
        run = runs.get(check.id)
        if run is None:
            continue
        if check.area != INVENTORY_AREA:
            # Metrics and other checks do not depend on the reference: keep what was saved.
            result = CheckResult(
                check_id=check.id,
                status=run.status,
                summary=run.summary,
                metrics=store.metrics(snapshot.id, check.id),
                error=run.error,
                duration_ms=run.duration_ms,
            )
            outcomes.append(CheckOutcome(check.id, check.label, check.area, result))
            continue
        failed = run.raw_status.is_failure
        result = CheckResult(
            check_id=check.id,
            status=run.raw_status if failed else Status.OK,
            summary=run.summary if failed else run.raw_summary,
            items=[] if failed else list(store.items(snapshot.id, check.id).values()),
            error=run.error,
            duration_ms=run.duration_ms,
        )
        outcomes.append(
            analyse(store, check, result, snapshot.is_admin, reference, snapshot.id, approvals)
        )
    return SnapshotReport(snapshot=snapshot, outcomes=outcomes, reference=reference)
