"""Терминальные запросы: выбор строк, ввод и подтверждение клавишами."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from modules.i18n import t as _tr

HELP_TEXT = _tr('tui.menu.help')


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding('y', 'answer(True)', '', show=False),
                Binding('n,escape,enter', 'answer(False)', '', show=False)]

    def __init__(self, text):
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes='terminal-dialog'):
            yield Static(self._text, markup=False)
            yield Static(_tr('tui.classic.confirm'), classes='prompt-keys', markup=False)

    def action_answer(self, value):
        self.dismiss(value)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding('escape,question_mark,enter', 'close', '', show=False)]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes='terminal-dialog help'):
            yield Static(HELP_TEXT, markup=False)
            yield Static(_tr('tui.screens.esc_to_close'), classes='prompt-keys', markup=False)

    def on_mount(self):
        self.query_one('.help', VerticalScroll).focus()

    def action_close(self):
        self.dismiss(None)


class PromptScreen(ModalScreen[str | None]):
    BINDINGS = [Binding('escape', 'cancel', '', show=False)]

    def __init__(self, title, value=''):
        super().__init__()
        self.title_text = title
        self.value = value

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes='terminal-dialog'):
            yield Static(self.title_text, markup=False)
            yield Input(value=self.value, id='prompt-input', select_on_focus=True)
            yield Static(_tr('tui.classic.input_keys'), classes='prompt-keys', markup=False)

    def on_mount(self):
        self.query_one(Input).focus()

    def on_input_submitted(self, event):
        event.stop()
        self.dismiss(event.value)

    def action_cancel(self):
        self.dismiss(None)


class MenuScreen(ModalScreen[str | None]):
    BINDINGS = [Binding('escape', 'cancel', '', show=False)]

    def __init__(self, title, choices):
        super().__init__()
        self.title_text = title
        self.choices = choices

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes='terminal-dialog'):
            yield Static(self.title_text, markup=False)
            yield OptionList(*(Option(Text(f'{i}. {label}'), id=key) for i, (key, label) in enumerate(self.choices, 1)), id='choices')
            yield Static(_tr('tui.classic.choice_keys'), classes='prompt-keys', markup=False)

    def on_mount(self):
        self.query_one(OptionList).focus()

    def on_key(self, event):
        if event.key.isdigit() and 1 <= int(event.key) <= min(9, len(self.choices)):
            event.stop()
            self.dismiss(self.choices[int(event.key) - 1][0])

    def on_option_list_option_selected(self, event):
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self):
        self.dismiss(None)


class ListPicker(ModalScreen[list | None]):
    BINDINGS = [Binding('escape', 'cancel', '', show=False),
                Binding('space', 'toggle', '', show=False, priority=True),
                Binding('enter', 'apply', '', show=False, priority=True)]

    def __init__(self, title, names, selected):
        super().__init__()
        self.title_text, self.names, self.selected = title, names, set(selected)

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes='terminal-dialog'):
            yield Static(self.title_text, markup=False)
            yield OptionList(*(self._option(name) for name in self.names), id='picker')
            yield Static(_tr('tui.classic.picker_keys'), classes='prompt-keys', markup=False)

    def _option(self, name):
        return Option(Text(f"[{'x' if name in self.selected else ' '}] {name}"), id=name)

    def on_mount(self):
        self.query_one(OptionList).focus()

    def action_toggle(self):
        menu = self.query_one(OptionList)
        if menu.highlighted is None:
            return
        name = menu.get_option_at_index(menu.highlighted).id
        self.selected.symmetric_difference_update({name})
        menu.replace_option_prompt(name, self._option(name).prompt)

    def action_apply(self):
        self.dismiss([name for name in self.names if name in self.selected])

    def action_cancel(self):
        self.dismiss(None)
