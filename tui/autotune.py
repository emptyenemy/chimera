"""Автонастройка в TUI: ход подбора, итог по сервисам и те же действия, что у `chimera fix`.

Экран ничего не подбирает сам: подбор идёт у владельца модулей (окно или служба), сюда
приходит его состояние из быстрого опроса приложения (источник autotune). Тексты — те же
строки, что печатает командная строка, чтобы терминал и TUI говорили одинаково.
"""

import webbrowser

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from modules.cli.commands import _fix_check_lines, _fix_progress, _fix_session_lines
from modules.i18n import t as _tr
from tui.screens import MenuScreen

RECOVER = ("interrupted", "rollback_failed")   # прошлая сессия не закрыта: сначала вернуть как было


def session_lines(state) -> list[str]:
    """Что показать о подборе: ход идущего или итог последнего."""
    active, last = (state or {}).get("active"), (state or {}).get("last")
    if active and active.get("phase") == "running":
        current = active.get("current")
        return [_tr("cli.fix.phase.running")] + ([_fix_progress(current)] if current else [])
    session = active or last
    return _fix_session_lines(session) if session else []


def progress_line(state) -> str | None:
    """Строка для главного меню, пока идёт подбор."""
    active = (state or {}).get("active")
    if not active or active.get("phase") != "running":
        return None
    current = active.get("current")
    return _tr("tui.autotune.running", progress=_fix_progress(current) if current else _tr("cli.fix.phase.running"))


class AutotuneScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "", show=False)]

    def __init__(self):
        super().__init__()
        self.check = []       # строки последнего диагноза «Проверить»
        self.actions = {}
        self.shown = None

    def compose(self) -> ComposeResult:
        yield Static(_tr("tui.autotune.title"), id="autotune-title", markup=False)
        with VerticalScroll(id="autotune-report"):
            yield Static("", id="autotune-text", markup=False)
        yield OptionList(id="autotune-actions")
        yield Static(_tr("tui.autotune.keys"), classes="prompt-keys", markup=False)

    def on_mount(self):
        self.render_state()
        self.query_one(OptionList).focus()
        self.set_interval(0.5, self.render_state)

    def state(self):
        return self.app.data("autotune") or {}

    def render_state(self):
        state = self.state()
        lines = session_lines(state) or [_tr("tui.autotune.idle")]
        if self.check:
            lines += [""] + self.check
        self.query_one("#autotune-text", Static).update("\n".join(lines))
        entries = self.entries(state)
        if [key for key, _, _ in entries] != self.shown:
            self.shown = [key for key, _, _ in entries]
            self.actions = {key: action for key, _, action in entries}
            menu = self.query_one(OptionList)
            menu.clear_options()
            menu.add_options(Option(Text(f"{i:>2}. {label}"), id=key) for i, (key, label, _) in enumerate(entries, 1))
            menu.highlighted = 0

    def entries(self, state):
        active, last = state.get("active"), state.get("last")
        phase = (active or {}).get("phase")
        if phase == "running":
            return [("cancel", _tr("tui.autotune.cancel"), lambda: self.run("autotune_cancel", "fix cancel"))]
        entries = []
        if phase == "done":
            entries += [("keep", _tr("tui.autotune.keep"), lambda: self.run("autotune_keep", "fix keep")),
                        ("revert", _tr("tui.autotune.revert"), lambda: self.run("autotune_revert", "fix revert"))]
        elif phase in RECOVER:
            entries.append(("revert", _tr("tui.autotune.revert"), lambda: self.run("autotune_revert", "fix revert")))
        entries += [("fast", _tr("tui.autotune.fast"), lambda: self.start(None, "fast")),
                    ("smart", _tr("tui.autotune.smart"), lambda: self.start(None, "smart")),
                    ("one", _tr("tui.autotune.fix_one"), self.one),
                    ("check", _tr("tui.autotune.check"), self.diagnose)]
        if (active or last or {}).get("report"):
            entries.append(("share", _tr("tui.autotune.share"), self.share))
        return entries

    def on_key(self, event):
        # цифра — пункт меню, как в разделах: окно модальное, цифры приложения сюда не доходят
        menu = self.query_one(OptionList)
        if event.key.isdigit() and 1 <= int(event.key) <= min(9, menu.option_count):
            event.stop()
            menu.highlighted = int(event.key) - 1
            menu.action_select()

    def on_option_list_option_selected(self, event):
        event.stop()
        action = self.actions.get(event.option.id)
        if action:
            action()

    def run(self, method, journal, *args):
        self.check = []
        self.app.act(_tr("tui.autotune.title"), method, *args, journal=journal)

    def start(self, services, mode):
        self.run("autotune_start", f"fix {mode} {' '.join(services or [])}".strip(), services, mode)

    def one(self):
        def loaded(catalog):
            names = [item["name"] for item in catalog or []]
            self.app.push_screen(MenuScreen(_tr("tui.autotune.choose_service"), [(n, n) for n in names]),
                                 lambda name: self.start([name], "fast") if name else None)
        self.app.act(_tr("tui.autotune.title"), "autotune_catalog", after=loaded, record=False)

    def diagnose(self):
        def done(data):
            self.check = _fix_check_lines(data or {})
            self.render_state()
        self.app.act(_tr("tui.autotune.check"), "autotune_diagnose", None, after=done, record=False)

    def share(self):
        def done(report):
            url = report.get("url") or report.get("form")
            opened = False
            try:
                opened = webbrowser.open(url)
            except Exception:  # noqa: BLE001 — терминал без браузера (SSH): ссылку покажем текстом
                opened = False
            # длинный отчёт в ссылку не влез, а без браузера ссылку не открыть: текст печатает команда
            self.app.status(_tr("tui.autotune.shared") if opened and report.get("url") else _tr("tui.autotune.share_cli"))
        self.app.act(_tr("tui.autotune.share"), "autotune_share", after=done, record=False)

    def action_close(self):
        self.dismiss(None)
