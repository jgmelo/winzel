"""Modal dialogs: new milestone, approve a change, confirm an action."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

DIALOG_CSS = """
.dialog { width: 72; height: auto; border: thick $primary; background: $surface; padding: 1 2; }
.dialog .title { text-style: bold; margin-bottom: 1; }
.dialog Input { margin-bottom: 1; }
.dialog .error { color: $error; height: auto; }
.dialog .details { height: auto; max-height: 16; }
.dialog .buttons { height: auto; align-horizontal: right; margin-top: 1; }
.dialog Button { margin-left: 2; }
"""


class _Dialog[T](ModalScreen[T]):
    DEFAULT_CSS = DIALOG_CSS
    BINDINGS: ClassVar = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self) -> None:
        super().__init__()
        self.styles.align = ("center", "middle")

    def action_cancel(self) -> None:
        self.dismiss(None)


class MilestoneDialog(_Dialog[object]):
    """Asks for name and note; `create(name, note)` saves it or raises ValueError."""

    def __init__(self, snapshot_text: str, create: Callable[[str, str], object]) -> None:
        super().__init__()
        self.snapshot_text = snapshot_text
        self.create = create

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Novo milestone — fixa o {self.snapshot_text}", classes="title")
            yield Input(placeholder="Nome (obrigatório)", id="milestone-name")
            yield Input(placeholder="Nota (opcional)", id="milestone-note")
            yield Static("", id="milestone-error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Cancelar", id="cancel")
                yield Button("Criar", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#milestone-name", Input).focus()

    def submit(self) -> None:
        name = self.query_one("#milestone-name", Input).value
        note = self.query_one("#milestone-note", Input).value
        try:
            created = self.create(name, note)
        except ValueError as exc:
            self.query_one("#milestone-error", Static).update(str(exc).capitalize() + ".")
            return
        self.dismiss(created)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.submit()
        else:
            self.dismiss(None)


class ApproveDialog(_Dialog[str]):
    """Asks for an optional reason; returns it ("" when empty) or None if cancelled."""

    def __init__(self, description: str) -> None:
        super().__init__()
        self.description = description

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Aprovar: {self.description}", classes="title")
            yield Input(placeholder="Motivo (opcional)", id="approve-reason")
            with Horizontal(classes="buttons"):
                yield Button("Cancelar", id="cancel")
                yield Button("Aprovar", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#approve-reason", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self.query_one("#approve-reason", Input).value)
        else:
            self.dismiss(None)


class ConfirmDialog(_Dialog[bool]):
    """Explicit confirmation: returns True only when the user presses the confirm button."""

    def __init__(self, question: str, confirm_label: str, details: str = "") -> None:
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label
        self.details = details

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question, classes="title")
            if self.details:
                with VerticalScroll(classes="details"):
                    yield Static(self.details, id="confirm-details", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Cancelar", id="cancel")
                yield Button(self.confirm_label, id="ok", variant="error")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)
