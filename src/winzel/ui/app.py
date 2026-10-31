"""Textual application: progress, Visão geral and Mudanças tabs, milestones and approvals."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Select, Static, TabbedContent, TabPane

from ..cli import ADMIN_WARNING, KIND_LABELS
from ..config import use_emoji
from ..context import Context
from ..diff import Change, ChangeKind
from ..models import Check
from ..reference import (
    Reference,
    available_references,
    default_reference,
    reference_by_value,
)
from ..snapshot import CheckOutcome, SnapshotReport, compare_snapshot, take_snapshot
from ..status import format_date
from ..store import Store
from .dialogs import ApproveDialog, ConfirmDialog, MilestoneDialog

ALL = "all"
PENDING_ONLY = "pending"
PENDING = "⏳"
TABS = ["overview", "changes"]

SnapshotFn = Callable[..., SnapshotReport]


def filter_changes(
    changes: list[Change], category: str = ALL, kind: str = ALL, situation: str = ALL
) -> list[Change]:
    """Changes of one category, kind and/or situation (pending only); ALL keeps everything."""
    return [
        c
        for c in changes
        if (category == ALL or c.category == category)
        and (kind == ALL or c.kind.value == kind)
        and (situation == ALL or not c.approved)
    ]


def versions_text(change: Change) -> str:
    if change.old_version is not None and change.new_version is not None:
        return f"{change.old_version} → {change.new_version}"
    return change.new_version or change.old_version or ""


def change_description(change: Change, category_label: str) -> str:
    return f"{change.kind.symbol} {change.name} ({category_label}, {change.kind.label})"


class WinzelApp(App[None]):
    TITLE = "winzel"
    CSS = """
    #progress { padding: 1 2; height: auto; }
    #progress-title { text-style: bold; margin-bottom: 1; }
    #overview-header { padding: 0 1; margin-bottom: 1; }
    #admin-warning { padding: 0 1; color: $warning; margin-bottom: 1; }
    .card { border: round $panel-lighten-2; padding: 0 1; margin: 0 1; height: auto; }
    .card.status-warn { border: round $warning; }
    .card.status-problem, .card.status-error { border: round $error; }
    #filters { height: auto; padding: 0 1; }
    #filters Select { width: 26; margin-right: 1; }
    #filters #filter-reference { width: 44; }
    #reference-note { padding: 0 2; color: $text-muted; height: auto; }
    #changes-empty { padding: 1 2; color: $text-muted; }
    """
    BINDINGS: ClassVar = [
        Binding("q", "quit", "Sair"),
        Binding("r", "refresh", "Atualizar"),
        Binding("m", "milestone", "Novo milestone"),
        Binding("a", "approve", "Aprovar"),
        Binding("d", "delete_milestone", "Apagar milestone"),
        Binding("tab", "next_tab", "Trocar de aba", priority=True),
    ]

    def __init__(
        self,
        store: Store,
        ctx: Context,
        checks: list[Check],
        snapshot_fn: SnapshotFn = take_snapshot,
    ) -> None:
        super().__init__()
        self.store = store
        self.ctx = ctx
        self.checks = checks
        self.snapshot_fn = snapshot_fn
        self.emoji = use_emoji(ctx.config)
        self.report: SnapshotReport | None = None
        self.reference: Reference | None = None
        self.shown_changes: list[Change] = []
        self.busy = False
        self._reference_value: str | None = None

    # --- layout -------------------------------------------------------------

    def category_options(self) -> list[tuple[str, str]]:
        """Options of the category filter: all, then each inventory check."""
        return [("Todas as categorias", ALL)] + [
            (c.label, c.id) for c in self.checks if c.area == "inventario"
        ]

    def reference_options(self) -> list[tuple[str, str]]:
        return [(r.label, r.value) for r in available_references(self.store)]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="progress"):
            yield Static("Executando checagens…", id="progress-title")
            for check in self.checks:
                yield Static(id=f"progress-{check.id}", classes="progress-line")
        with TabbedContent(id="tabs"):
            with TabPane("Visão geral", id="overview"):
                yield VerticalScroll(id="overview-body")
            with TabPane("Mudanças", id="changes"):
                with Horizontal(id="filters"):
                    yield Select([], prompt="Referência", id="filter-reference")
                    kinds = [("Todos os tipos", ALL)] + [
                        (f"{k.symbol} {k.label.capitalize()}s", k.value) for k in ChangeKind
                    ]
                    situations = [("Todas", ALL), ("Pendentes", PENDING_ONLY)]
                    yield Select(
                        self.category_options(),
                        value=ALL,
                        allow_blank=False,
                        id="filter-category",
                    )
                    yield Select(kinds, value=ALL, allow_blank=False, id="filter-kind")
                    yield Select(situations, value=ALL, allow_blank=False, id="filter-situation")
                yield Static("", id="reference-note")
                yield Static("", id="changes-empty")
                yield DataTable(id="changes-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#changes-table", DataTable)
        table.add_columns("Tipo", "Categoria", "Item", "Versão anterior → atual", "Aprovação")
        self.start_snapshot()

    # --- snapshot -----------------------------------------------------------

    def start_snapshot(self) -> None:
        self.busy = True
        for check in self.checks:
            self.query_one(f"#progress-{check.id}", Static).update(f"{PENDING} {check.label}")
        self.query_one("#progress").display = True
        self.query_one("#tabs").display = False
        self._snapshot_worker()

    @work(thread=True, exclusive=True, group="snapshot")
    def _snapshot_worker(self) -> None:
        try:
            report = self.snapshot_fn(
                self.store,
                self.ctx,
                self.checks,
                "auto",
                on_progress=lambda o: self.call_from_thread(self._on_progress, o),
                reference=self.reference,
            )
        except Exception as exc:  # show it instead of crashing the interface
            self.call_from_thread(self._on_failure, exc)
            return
        self.call_from_thread(self._show_report, report)

    def _on_progress(self, outcome: CheckOutcome) -> None:
        line = self.query_one(f"#progress-{outcome.check_id}", Static)
        line.update(
            f"{outcome.status.symbol(self.emoji)} {outcome.label} — {outcome.result.summary}"
        )

    def _on_failure(self, exc: Exception) -> None:
        self.busy = False
        self.query_one("#progress-title", Static).update(
            f"Falha ao gravar o snapshot: {exc}. Pressione r para tentar de novo."
        )

    async def _show_report(self, report: SnapshotReport) -> None:
        self.busy = False
        # Right after the first snapshot the reference becomes the new linha-de-base.
        self.reference = report.reference or default_reference(self.store)
        await self._show_snapshot_report(report)
        self.query_one("#progress").display = False
        self.query_one("#tabs").display = True

    async def _show_snapshot_report(self, report: SnapshotReport) -> None:
        self.report = report
        self._refresh_reference_selector()
        await self._render_overview()
        self.refresh_changes()

    async def recompare(self, reference: Reference | None = None) -> None:
        """Compare the snapshot on screen with `reference` (default: the current one)."""
        if self.report is None:
            return
        if reference is not None:
            self.reference = reference
        report = compare_snapshot(self.store, self.checks, self.report.snapshot, self.reference)
        await self._show_snapshot_report(report)

    # --- Visão geral --------------------------------------------------------

    async def _render_overview(self) -> None:
        report = self.report
        assert report is not None
        snap = report.snapshot
        body = self.query_one("#overview-body", VerticalScroll)
        await body.remove_children()
        overall = report.overall_status
        widgets = [
            Static(
                f"Snapshot #{snap.id} ({KIND_LABELS.get(snap.kind, snap.kind)}) em "
                f"{format_date(snap.created_at)} · Referência: {report.reference_label} · "
                f"Status geral: {overall.symbol(self.emoji)} {overall.label}",
                id="overview-header",
            )
        ]
        if not snap.is_admin:
            widgets.append(Static(f"⚠ {ADMIN_WARNING}", id="admin-warning"))
        for o in report.outcomes:
            text = f"{o.status.symbol(self.emoji)} [b]{o.label}[/b]\n{o.result.summary}"
            widgets.append(
                Static(text, classes=f"card status-{o.status.value}", id=f"card-{o.check_id}")
            )
        await body.mount_all(widgets)

    # --- Mudanças -----------------------------------------------------------

    def _refresh_reference_selector(self) -> None:
        select = self.query_one("#filter-reference", Select)
        options = self.reference_options()
        value = self.reference.value if self.reference else options[0][1]
        self._reference_value = value
        select.set_options(options)
        select.value = value
        note = self.reference.milestone.note if self.reference and self.reference.milestone else ""
        self.query_one("#reference-note", Static).update(f"Nota: {note}" if note else "")

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "filter-reference":
            value = event.value
            if value == self._reference_value or value is Select.BLANK:
                return
            reference = reference_by_value(self.store, str(value))
            if reference is not None:
                await self.recompare(reference)
            return
        self.refresh_changes()

    def visible_changes(self) -> list[Change]:
        if self.report is None:
            return []
        category = self.query_one("#filter-category", Select).value
        kind = self.query_one("#filter-kind", Select).value
        situation = self.query_one("#filter-situation", Select).value
        return filter_changes(self.report.changes, str(category), str(kind), str(situation))

    def refresh_changes(self) -> None:
        table = self.query_one("#changes-table", DataTable)
        table.clear()
        self.shown_changes = self.visible_changes()
        labels = {c.id: c.label for c in self.checks}
        for change in self.shown_changes:
            symbol = change.kind.symbol if self.emoji else change.kind.text_symbol
            mark = ("✔ aprovado" if self.emoji else "[aprovado]") if change.approved else ""
            table.add_row(
                f"{symbol} {change.kind.label}",
                labels.get(change.category, change.category),
                change.name,
                versions_text(change),
                mark,
            )
        empty = self.query_one("#changes-empty", Static)
        if self.shown_changes:
            empty.display = False
        else:
            empty.display = True
            total = len(self.report.changes) if self.report else 0
            reference = self.report.reference_label if self.report else "linha de base"
            if total:
                empty.update("Nenhuma mudança com estes filtros.")
            elif reference.startswith("linha de base"):
                empty.update("Nenhuma mudança em relação à linha de base.")
            else:
                empty.update(f"Nenhuma mudança em relação a: {reference}.")

    def selected_change(self) -> Change | None:
        table = self.query_one("#changes-table", DataTable)
        if not self.shown_changes or table.cursor_row is None:
            return None
        row = table.cursor_row
        return self.shown_changes[row] if 0 <= row < len(self.shown_changes) else None

    # --- actions ------------------------------------------------------------

    def _can_act(self) -> bool:
        if self.busy or self.report is None:
            self.notify("Aguarde o snapshot terminar.", severity="warning")
            return False
        return True

    def action_refresh(self) -> None:
        if not self.busy:
            self.start_snapshot()

    def action_next_tab(self) -> None:
        if isinstance(self.screen, ModalScreen):
            self.screen.focus_next()
            return
        tabs = self.query_one("#tabs", TabbedContent)
        if not tabs.display:
            return
        current = TABS.index(tabs.active) if tabs.active in TABS else -1
        tabs.active = TABS[(current + 1) % len(TABS)]
        if tabs.active == "changes":
            self.query_one("#changes-table", DataTable).focus()

    def action_milestone(self) -> None:
        if not self._can_act():
            return
        assert self.report is not None
        snap = self.report.snapshot
        text = f"snapshot #{snap.id} de {format_date(snap.created_at)}"

        def create(name: str, note: str):
            return self.store.create_milestone(snap.id, name, note, self.ctx.now())

        async def done(milestone) -> None:
            if milestone is None:
                return
            self.notify(f"Milestone {milestone.name} criado.")
            await self.recompare(Reference.of_milestone(milestone))

        self.push_screen(MilestoneDialog(text, create), done)

    def action_approve(self) -> None:
        if not self._can_act():
            return
        tabs = self.query_one("#tabs", TabbedContent)
        change = self.selected_change() if tabs.active == "changes" else None
        if change is None:
            self.notify("Selecione uma mudança na aba Mudanças.", severity="warning")
            return
        if not change.approvable:
            self.notify("Mudanças de versão são informativas e não precisam de aprovação.")
            return
        labels = {c.id: c.label for c in self.checks}
        description = change_description(change, labels.get(change.category, change.category))
        category, key, kind = change.approval_key

        if change.approved:

            async def revoked(confirmed: bool | None) -> None:
                if confirmed:
                    self.store.revoke(category, key, kind)
                    self.notify("Aprovação revogada.")
                    await self.recompare()

            self.push_screen(
                ConfirmDialog(f"Revogar a aprovação de {description}?", "Revogar"), revoked
            )
            return

        async def approved(reason: str | None) -> None:
            if reason is None:
                return
            self.store.approve(category, key, kind, reason, self.ctx.now())
            self.notify("Mudança aprovada.")
            await self.recompare()

        self.push_screen(ApproveDialog(description), approved)

    def action_delete_milestone(self) -> None:
        if not self._can_act():
            return
        milestone = self.reference.milestone if self.reference else None
        if milestone is None:
            self.notify(
                "Escolha, no seletor da aba Mudanças, o milestone a apagar.", severity="warning"
            )
            return
        if milestone.is_baseline:
            self.notify("A linha de base não pode ser apagada.", severity="warning")
            return

        async def confirmed(answer: bool | None) -> None:
            if not answer:
                return
            self.store.delete_milestone(milestone.name)
            self.notify(f"Milestone {milestone.name} apagado.")
            await self.recompare(default_reference(self.store))

        self.push_screen(
            ConfirmDialog(
                f"Apagar o milestone {milestone.name}? Esta ação não pode ser desfeita.",
                "Apagar",
            ),
            confirmed,
        )
