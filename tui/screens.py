"""Диалоги разделов: подтверждение, подсказка по клавишам, выбор списков."""

from modules.i18n import t as _tr

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, SelectionList, Static

HELP_TEXT = _tr('tui.menu.help')


class ConfirmScreen(ModalScreen[bool]):
    """Вопрос «да/нет». Фокус по умолчанию на «Нет»: случайный Enter ничего не ломает."""

    BINDINGS = [
        Binding("y", "answer(True)", _tr('tui.screens.yes'), show=False),
        Binding("n,escape", "answer(False)", _tr('tui.screens.no'), show=False),
    ]

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(escape(self._text), classes="dialog-text")
            with Horizontal(classes="dialog-buttons"):
                yield Button(_tr('tui.screens.yes_y'), id="yes")
                yield Button(_tr('tui.screens.no_n'), id="no")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,enter", "close", _tr('tui.screens.close'), show=False)]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog help"):
            yield Static(HELP_TEXT, markup=False, classes="dialog-text")
            yield Static(_tr('tui.screens.esc_to_close'), classes="dim")

    def action_close(self) -> None:
        self.dismiss(None)


class ListPicker(ModalScreen[list | None]):
    """Выбор списков для провайдера hosts. Результат — имена отмеченных или None (отмена)."""

    BINDINGS = [Binding("escape", "cancel", _tr('tui.screens.cancel'), show=False)]

    def __init__(self, title: str, names: list[str], selected: list[str]):
        super().__init__()
        self._title = title
        self._names = names
        self._selected = set(selected)

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(escape(self._title), classes="dialog-text")
            yield SelectionList(*[(n, n, n in self._selected) for n in self._names], id="picker")
            with Horizontal(classes="dialog-buttons"):
                yield Button(_tr('tui.screens.apply'), id="ok")
                yield Button(_tr('tui.screens.cancel'), id="cancel")

    def on_mount(self) -> None:
        self.query_one("#picker", SelectionList).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self.dismiss(list(self.query_one("#picker", SelectionList).selected))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
