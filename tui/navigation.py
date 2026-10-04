"""Клавиатурное меню и навигация по элементам разделов."""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from modules.i18n import t
from tui.autotune import progress_line

LOGO = r"""          .---.
   .--.  / .-. \     ____   _  _   ___  __   __  ____   ____      _
  / .-.\ / /_/_/    / ___| | || | |_ _| | \ / | | ___| |  _ \    / \
  | '-'/ /\         | |    | __ |  | |  |  V  | | _|   | |_) |  / _ \
   '---'  \ \       | |__  | || |  | |  | | | | | |__  |  _ <  / ___ \
       .-./ |       \____| |_||_| |___| |_| |_| |____| |_| \_\ /_/ \_\
       \___/"""
LOGO_WIDTH = max(map(len, LOGO.splitlines()))


def editing(widget) -> bool:
    return isinstance(widget, (Input, TextArea))


def move_focus(screen, direction: str) -> None:
    widget = screen.focused
    if isinstance(widget, OptionList):
        if direction == "right":
            widget.action_select()
        elif direction == "left":
            screen.app.action_back()
        else:
            getattr(widget, f"action_cursor_{direction}")()
    elif isinstance(widget, (RichLog, VerticalScroll)) and direction in ("up", "down"):
        getattr(widget, f"action_scroll_{direction}")()


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
        full = height >= 30 and self.content_size.width >= LOGO_WIDTH
        logo = self.query_one("#logo", Static)
        logo.styles.height = len(LOGO.splitlines()) if full else 1
        logo.update(LOGO if full else "C H I M E R A")
        self.query_one("#tagline", Static).display = height >= 26

    def on_resize(self) -> None:
        self.compact(self.app.size.height)

    def render_state(self) -> None:
        active = []
        for key, title in (("winws", "DPI"), ("proxy", t("tui.textual_app.proxy")), ("tg", "Telegram"), ("hosts_state", "Hosts")):
            state = self.app.data(key) or {}
            if state.get("running") or (key == "hosts_state" and state.get("applied")):
                active.append(title)
        summary = t("tui.menu.active", modules=" · ".join(active)) if active else t("tui.menu.idle")
        progress = progress_line(self.app.data("autotune"))
        self.query_one("#home-summary", Static).update(summary + (f"\n{progress}" if progress else ""))
