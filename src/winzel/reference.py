"""What a snapshot is compared with: a milestone or the previous snapshot (SPEC 8.4)."""

from __future__ import annotations

from dataclasses import dataclass

from .status import format_date
from .store import MilestoneInfo, SnapshotInfo, Store

PREVIOUS = "previous"
MILESTONE = "milestone"


@dataclass(frozen=True)
class Reference:
    kind: str
    milestone: MilestoneInfo | None = None

    @classmethod
    def of_milestone(cls, milestone: MilestoneInfo) -> Reference:
        return cls(MILESTONE, milestone)

    @classmethod
    def previous(cls) -> Reference:
        return cls(PREVIOUS)

    @property
    def value(self) -> str:
        """Stable identifier, used by the interface selector."""
        return f"m:{self.milestone.name}" if self.milestone else PREVIOUS

    @property
    def label(self) -> str:
        if self.milestone is None:
            return "último snapshot"
        when = format_date(self.milestone.snapshot.created_at)
        if self.milestone.is_baseline:
            return f"linha de base ({when})"
        return f"milestone {self.milestone.name} ({when})"

    def since(self, effective: SnapshotInfo) -> str:
        """Text after "desde": names the reference and the date actually compared."""
        when = format_date(effective.created_at)
        if self.milestone is None:
            return f"o último snapshot ({when})"
        if self.milestone.is_baseline:
            return f"a linha de base ({when})"
        return f"o milestone {self.milestone.name} ({when})"

    def resolve(self, store: Store, check_id: str, current_id: int | None) -> SnapshotInfo | None:
        """Snapshot this category is compared with.

        Milestone: the first snapshot from the milestone on where the category was
        collected (an error on the milestone's day does not make it useless).
        Previous: the last snapshot before the current one where it was collected.
        """
        if self.milestone is None:
            return store.reference_before(check_id, current_id)
        return store.reference_from(check_id, self.milestone.snapshot.id, up_to=current_id)


def default_reference(store: Store) -> Reference | None:
    """The most recent milestone; None while there is no snapshot at all."""
    latest = store.latest_milestone()
    return Reference.of_milestone(latest) if latest else None


def reference_by_value(store: Store, value: str) -> Reference | None:
    if value == PREVIOUS:
        return Reference.previous()
    if value.startswith("m:"):
        found = store.milestone(value[2:])
        return Reference.of_milestone(found) if found else None
    return None


def reference_by_name(store: Store, name: str) -> Reference | None:
    """CLI form: a milestone name, or "ultimo"/"último" for the previous snapshot."""
    if name.strip().lower() in ("ultimo", "último"):
        return Reference.previous()
    found = store.milestone(name)
    return Reference.of_milestone(found) if found else None


def available_references(store: Store) -> list[Reference]:
    return [Reference.of_milestone(m) for m in store.milestones()] + [Reference.previous()]
