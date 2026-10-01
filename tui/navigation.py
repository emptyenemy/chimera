"""Клавиатурное меню и навигация по элементам разделов."""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Input, OptionList, RadioSet, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from modules.i18n import t

LOGO = r"""   _____ _    _ _____ __  __ ______ _____
  / ____| |  | |_   _|  \/  |  ____|  __ \     /\
 | |    | |__| | | | | \  / | |__  | |__) |   /  \
 | |____|  __  |_| |_| |\/| |  __| |  _  /   / /\ \
  \_____|_|  |_|_____|_|  |_|______|_| \_\  /_/  \_\ """


def editing(widget) -> bool:
    return isinstance(widget, (Input, TextArea))


def move_focus(screen, direction: str) -> None:
    """Стрелки/WASD в таблицах двигают курсор, в формах — фокус."""
    widget = screen.focused
    if isinstance(widget, RadioSet):
        if direction in ("up", "left"):
            widget.action_previous_button()
        else:
            widget.action_next_button()
    elif isinstance(widget, (DataTable, OptionList)):
        action = getattr(widget, f"action_cursor_{direction}", None)
        if action is not None:
            action()
    elif isinstance(widget, RichLog) and direction in ("up", "down"):
        getattr(widget, f"action_scroll_{direction}")()
    elif direction in ("up", "left"):
        screen.focus_previous()
    else:
        screen.focus_next()


class HomeMenu(VerticalScroll):
    def __init__(self, sections):
        super().__init__(id="home")
        self.sections = sections

    def compose(self) -> ComposeResult:
        yield Static(LOGO, id="logo", markup=False)
        yield Static(t("tui.menu.tagline"), id="tagline", markup=False, classes="dim")
        yield Static("", id="home-summary", markup=False)
        yield OptionList(*(Option(f"  {i}  {title}", id=sid) for i, (sid, title, _) in enumerate(self.sections, 1)), id="menu")
        yield Static("", id="menu-description", markup=False, classes="dim")

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).highlighted = 0

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.query_one("#menu-description", Static).update(t("tui.menu.description" + "." + event.option.id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.app.open_section(event.option.id)

    def compact(self, height: int) -> None:
        self.query_one("#logo", Static).update("C H I M E R A" if height < 30 else LOGO)
        self.query_one("#tagline", Static).display = height >= 26

    def render_state(self) -> None:
        active = []
        for key, title in (("winws", "DPI"), ("proxy", t("tui.textual_app.proxy")), ("tg", "Telegram"), ("hosts_state", "Hosts")):
            state = self.app.data(key) or {}
            if state.get("running") or (key == "hosts_state" and state.get("applied")):
                active.append(title)
        summary = t("tui.menu.active", modules=" · ".join(active)) if active else t("tui.menu.idle")
        self.query_one("#home-summary", Static).update(summary)
