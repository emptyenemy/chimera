"""Окна поверх вкладок: подтверждение, подсказка по клавишам, выбор списков."""

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, SelectionList, Static

HELP_TEXT = """\
Вкладки
  1-9          перейти на вкладку по номеру
  Tab          следующая вкладка
  Shift+Tab    предыдущая вкладка
  f            следующий элемент внутри вкладки
  мышь         клик по вкладке, строке, переключателю

В таблицах и списках
  стрелки      выбор строки
  Enter        выбрать / применить
  Пробел       переключить отмеченное (вкладка «Списки»)
  /            поиск (вкладка «Стратегии»)
  e            править список во внешнем редакторе ($EDITOR, иначе notepad)
  x            остановить обход (вкладка «Стратегии»)
  r            вернуть DNS адаптера на DHCP (вкладка «DNS»)
  Delete       убрать приложение (вкладка «Прокси»)

Общее
  ?            эта подсказка
  q            выход из TUI (Chimera продолжает работать)

Изменения системы (hosts, DNS, TUN, запуск обхода) выполняются теми же методами, что и
команды `chimera`. Секреты и ссылки прокси на экране скрыты.\
"""


class ConfirmScreen(ModalScreen[bool]):
    """Вопрос «да/нет». Фокус по умолчанию на «Нет»: случайный Enter ничего не ломает."""

    BINDINGS = [
        Binding("y", "answer(True)", "Да", show=False),
        Binding("n,escape", "answer(False)", "Нет", show=False),
    ]

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(escape(self._text), classes="dialog-text")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Да (y)", id="yes")
                yield Button("Нет (n)", id="no")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,enter", "close", "Закрыть", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog help"):
            yield Static(HELP_TEXT, markup=False, classes="dialog-text")
            yield Static("Esc — закрыть", classes="dim")

    def action_close(self) -> None:
        self.dismiss(None)


class ListPicker(ModalScreen[list | None]):
    """Выбор списков для провайдера hosts. Результат — имена отмеченных или None (отмена)."""

    BINDINGS = [Binding("escape", "cancel", "Отмена", show=False)]

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
                yield Button("Применить", id="ok")
                yield Button("Отмена", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self.dismiss(list(self.query_one("#picker", SelectionList).selected))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
