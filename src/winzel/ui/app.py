"""Textual application: progress, Visão geral and Mudanças tabs."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Select, Static, TabbedContent, TabPane

from ..cli import ADMIN_WARNING, KIND_LABELS
from ..config import use_emoji
from ..context import Context
from ..diff import Change, ChangeKind
from ..models import Check
from ..snapshot import CheckOutcome, SnapshotReport, take_snapshot
from ..status import format_date
from ..store import Store

ALL = "all"
PENDING = "⏳"
TABS = ["overview", "changes"]

SnapshotFn = Callable[..., SnapshotReport]


def filter_changes(changes: list[Change], category: str = ALL, kind: str = ALL) -> list[Change]:
    """Changes of one category and/or kind; ALL keeps everything."""
    return [
        c
        for c in changes
        if (category == ALL or c.category == category) and (kind == ALL or c.kind.value == kind)
    ]


def versions_text(change: Change) -> str:
    if change.old_version is not None and change.new_version is not None:
        return f"{change.old_version} → {change.new_version}"
    return change.new_version or change.old_version or ""


class WinzelApp(App[None]):
    TITLE = "winzel"
    CSS = """
    #progress { padding: 1 2; height: auto; }
    #progress-title { text-style: bold; margin-bottom: 1; }
    #overview-header { padding: 0 1; margin-bottom: 1; }
    #admin-warning { padding: 0 1; color: $warning; margin-bottom: 1; }
    .card { border: round $panel-lighten-2; padding: 0 1; margin: 0 1 1 1; height: auto; }
    .card.status-warn { border: round $warning; }
    .card.status-problem, .card.status-error { border: round $error; }
    #filters { height: auto; padding: 0 1; }
    #filters Select { width: 32; margin-right: 2; }
    #changes-empty { padding: 1 2; color: $text-muted; }
    """
    BINDINGS: ClassVar = [
        Binding("q", "quit", "Sair"),
        Binding("r", "refresh", "Atualizar"),
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
        self.busy = False

    # --- layout -------------------------------------------------------------

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
                    categories = [("Todas as categorias", ALL)] + [
                        (c.label, c.id) for c in self.checks if c.area == "inventario"
                    ]
                    kinds = [("Todos os tipos", ALL)] + [
                        (f"{k.symbol} {k.label.capitalize()}s", k.value) for k in ChangeKind
                    ]
                    yield Select(categories, value=ALL, allow_blank=False, id="filter-category")
                    yield Select(kinds, value=ALL, allow_blank=False, id="filter-kind")
                yield Static("", id="changes-empty")
                yield DataTable(id="changes-table", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#changes-table", DataTable)
        table.add_columns("Tipo", "Categoria", "Item", "Versão anterior → atual")
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
        self.report = report
        self.busy = False
        snap = report.snapshot
        body = self.query_one("#overview-body", VerticalScroll)
        await body.remove_children()
        overall = report.overall_status
        widgets = [
            Static(
                f"Snapshot #{snap.id} ({KIND_LABELS.get(snap.kind, snap.kind)}) em "
                f"{format_date(snap.created_at)} · Referência: linha de base · "
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
        self.refresh_changes()
        self.query_one("#progress").display = False
        self.query_one("#tabs").display = True

    # --- Mudanças -----------------------------------------------------------

    def on_select_changed(self, _: Select.Changed) -> None:
        self.refresh_changes()

    def visible_changes(self) -> list[Change]:
        if self.report is None:
            return []
        category = self.query_one("#filter-category", Select).value
        kind = self.query_one("#filter-kind", Select).value
        return filter_changes(self.report.changes, str(category), str(kind))

    def refresh_changes(self) -> None:
        table = self.query_one("#changes-table", DataTable)
        table.clear()
        changes = self.visible_changes()
        labels = {c.id: c.label for c in self.checks}
        for change in changes:
            symbol = change.kind.symbol if self.emoji else change.kind.text_symbol
            table.add_row(
                f"{symbol} {change.kind.label}",
                labels.get(change.category, change.category),
                change.name,
                versions_text(change),
            )
        empty = self.query_one("#changes-empty", Static)
        if changes:
            empty.display = False
        else:
            empty.display = True
            total = len(self.report.changes) if self.report else 0
            empty.update(
                "Nenhuma mudança com estes filtros."
                if total
                else "Nenhuma mudança em relação à linha de base."
            )

    # --- actions ------------------------------------------------------------

    def action_refresh(self) -> None:
        if not self.busy:
            self.start_snapshot()

    def action_next_tab(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        if not tabs.display:
            return
        current = TABS.index(tabs.active) if tabs.active in TABS else -1
        tabs.active = TABS[(current + 1) % len(TABS)]
