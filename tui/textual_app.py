"""Полноэкранный TUI на Textual: клиент работающей Chimera (`chimera tui`).

Приложение не создаёт свой Api и не владеет процессами: все данные и действия идут через
tui/remote.py теми же методами, что у командной строки. Выход из TUI (q) Chimera не
останавливает.

Живое состояние — фоновые воркеры Textual раз в ~1 с (в потоках, интерфейс не блокируется):
  быстрый  — состояние модулей для «Обзора» и шапок вкладок;
  ленивый  — тяжёлое (списки, hosts, DNS, логи, настройки) только для открытой вкладки.
Во вкладки состояние попадает лишь при изменении. Нет связи — в шапке «нет связи с Chimera»,
опрос продолжается и подключается заново сам.
"""

from modules.i18n import t as _tr

import json
import os
import shlex
import subprocess
from collections import Counter

from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Footer, Static, TabbedContent, TabPane

from tui import panes
from tui.remote import Offline, RemoteError
from tui.screens import ConfirmScreen, HelpScreen

BASE_SOURCES = (("app", "app_info"), ("winws", "winws_state"), ("proxy", "proxy_state"),
                ("tg", "tg_state"), ("hosts_state", "hosts_state"))

TABS = (("overview", _tr('tui.textual_app.overview'), panes.OverviewPane), ("strategies", _tr('tui.textual_app.strategies'), panes.StrategiesPane),
        ("lists", _tr('tui.textual_app.lists'), panes.ListsPane), ("proxy", _tr('tui.textual_app.proxy'), panes.ProxyPane),
        ("hosts", "Hosts", panes.HostsPane), ("dns", "DNS", panes.DnsPane),
        ("tg", "Telegram", panes.TgPane), ("logs", _tr('tui.textual_app.logs'), panes.LogsPane),
        ("settings", _tr('tui.textual_app.settings'), panes.SettingsPane))

# Спокойная тёмная схема без цветного акцента (цветной акцент появится вместе с темами).
THEME = Theme(name="chimera", primary="#b9bdc5", secondary="#8d929b", accent="#b9bdc5", warning="#c2ae7d",
              error="#c98f8f", success="#93b59a", foreground="#d3d5da", background="#15171b",
              surface="#1b1e23", panel="#23262c", dark=True)

CSS = """
Screen { background: $background; }
#top { height: 1; padding: 0 1; background: $panel; color: $foreground; }
#top.offline { color: $error; }
#status { height: 1; padding: 0 1; color: $foreground 80%; }
#status.error { color: $error; }
TabbedContent { height: 1fr; }
TabPane { padding: 0 1; }
.dim { color: $foreground 55%; }
.hidden { display: none; }
.row { height: auto; margin: 0 0 1 0; }
.row .name { width: 24; padding: 1 1 0 0; }
.row .state { width: 1fr; padding: 1 1 0 0; }
Switch { border: none; padding: 0; margin: 1 2 0 0; }
Button { min-width: 18; }
DataTable { height: 1fr; min-height: 4; }
Input { margin: 0 0 1 0; }
RadioSet { border: none; padding: 0; margin: 0 0 1 0; }
RichLog { height: 1fr; }
Pane { height: 1fr; }
ModalScreen { align: center middle; }
.dialog { width: 70; height: auto; max-height: 90%; padding: 1 2; background: $panel; border: round $secondary; }
.dialog.help { width: 84; }
.dialog-text { margin: 0 0 1 0; }
.dialog-buttons { height: auto; }
.dialog-buttons Button { margin: 0 2 0 0; }
#picker { height: 12; margin: 0 0 1 0; }
"""


def run_editor(path) -> int:
    """Открывает файл во внешнем редакторе ($EDITOR, иначе notepad) и ждёт его закрытия."""
    cmd = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "notepad"
    return subprocess.run([*shlex.split(cmd, posix=False), str(path)], check=False).returncode


class ChimeraTui(App):
    TITLE = "Chimera"
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS
    BINDINGS = [
        Binding("q", "quit", _tr('tui.textual_app.quit')),
        Binding("ctrl+c", "quit", _tr('tui.textual_app.quit'), show=False, priority=True),
        Binding("question_mark", "help", _tr('tui.textual_app.help')),
        Binding("tab", "tab_step(1)", _tr('tui.textual_app.next_tab'), show=False, priority=True),
        Binding("shift+tab", "tab_step(-1)", _tr('tui.textual_app.previous_tab'), show=False, priority=True),
        *[Binding(str(i), f"goto({i})", TABS[i - 1][1], show=False) for i in range(1, len(TABS) + 1)],
    ]

    def __init__(self, remote, *, poll_interval: float = 1.0, editor=None, lists_dir=None):
        super().__init__()
        self.remote = remote
        self.poll_interval = poll_interval
        self.editor = editor or run_editor
        self._lists_dir = lists_dir
        self.link: bool | None = None      # None — ещё подключаемся
        self.link_note = ""
        self.status_text = ""
        self.pushes: Counter = Counter()   # сколько раз каждый источник менялся (для тестов)
        self._state: dict = {}
        self._seen: dict = {}
        self._tick = 0
        self._busy = {"fast": False, "slow": False}
        self._starting = True
        self._tabs = self._top = self._status = None
        self._force = False
        self._full_render = False

    # --- данные -------------------------------------------------------------------------

    def data(self, key: str):
        """Последнее известное состояние источника; None — не получено или источник вернул ошибку."""
        d = self._state.get(key)
        return None if isinstance(d, dict) and "_error" in d and len(d) == 1 else d

    def error(self, key: str) -> str | None:
        d = self._state.get(key)
        return d["_error"] if isinstance(d, dict) and "_error" in d and len(d) == 1 else None

    def forget(self, key: str) -> None:
        self._seen.pop(key, None)
        self._state.pop(key, None)

    @property
    def active_tab(self) -> str:
        return self._tabs.active

    def _panes(self) -> list:
        return list(self._tabs.query(panes.Pane))

    def _active_pane(self):
        return next((p for p in self._panes() if p.parent is not None and p.parent.id == self.active_tab), None)

    # --- вид ---------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("Chimera", id="top", markup=False)
        with TabbedContent(initial="overview", id="tabs"):
            for i, (tid, title, cls) in enumerate(TABS, 1):
                with TabPane(f"{i} {title}", id=tid):
                    yield cls()
        yield Static("", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        # ссылки на постоянные виджеты: поверх вкладок бывает окно (подтверждение, подсказка), и
        # query_one() у приложения ищет только на верхнем экране
        self._tabs = self.query_one(TabbedContent)
        self._top = self.query_one("#top", Static)
        self._status = self.query_one("#status", Static)
        self.register_theme(THEME)
        self.theme = "chimera"
        self._update_top()
        self.set_interval(self.poll_interval, self._on_tick)
        self.run_worker(self._startup, thread=True, name="startup")
        self._focus_pane()

    def _update_top(self) -> None:
        app = self._state.get("app") or {}
        ver = f" {app['version']}" if app.get("version") else ""
        note = {True: _tr('tui.textual_app.connected_to_chimera'), None: _tr('tui.textual_app.connecting_to_chimera')}.get(self.link)
        if self.link is False:
            note = _tr('tui.textual_app.no_connection_to_chimera')
            if self.link_note and self.link_note != note:
                note += f" ({self.link_note})"
        self._top.update(f"Chimera{ver} · {note}")
        self._top.set_class(self.link is False, "offline")

    def status(self, text: str, error: bool = False) -> None:
        self.status_text = text
        self._status.update(text)
        self._status.set_class(error, "error")

    def _focus_pane(self) -> None:
        pane = self._active_pane()
        if pane is not None:
            pane.focus_primary()

    # --- навигация -----------------------------------------------------------------------------

    def _blocked(self) -> bool:
        return isinstance(self.screen, ModalScreen)

    def action_goto(self, n: int) -> None:
        if not self._blocked() and 1 <= n <= len(TABS):
            self._tabs.active = TABS[n - 1][0]

    def action_tab_step(self, step: int) -> None:
        if self._blocked():
            return
        ids = [t[0] for t in TABS]
        self._tabs.active = ids[(ids.index(self.active_tab) + step) % len(ids)]

    def action_help(self) -> None:
        if not self._blocked():
            self.push_screen(HelpScreen())

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self.call_after_refresh(self._focus_pane)
        self.refresh_now(force=True)

    def confirm(self, text: str, on_yes) -> None:
        self.push_screen(ConfirmScreen(text), lambda ok: on_yes() if ok else None)

    # --- опрос ---------------------------------------------------------------------------------------

    def _startup(self) -> None:
        """Поднимает Chimera без окна, если она не запущена (как `chimera start`)."""
        try:
            self.remote.ensure_running(lambda m: self._post(self.status, m))
        except Offline as e:
            self._post(self._set_link, False, str(e))
        self._post(self._started)

    def _started(self) -> None:
        self._starting = False
        self.refresh_now(force=True)

    def _post(self, fn, *args) -> None:
        try:
            self.call_from_thread(fn, *args)
        except RuntimeError:
            pass  # приложение уже закрывается

    def _on_tick(self) -> None:
        self._tick += 1
        self.refresh_now()

    def refresh_now(self, force: bool = False) -> None:
        if self._starting:
            return
        self._force = self._force or force
        if not self._busy["fast"]:
            self._busy["fast"] = True
            self.run_worker(self._poll_fast, thread=True, name="poll-fast")
        if self.link is not False and not self._busy["slow"]:
            pane = self._active_pane()
            due = [s for s in (pane.sources() if pane else []) if self._force or self._tick % s[3] == 0]
            self._force = False
            if due:
                self._busy["slow"] = True
                self.run_worker(lambda: self._poll_slow(due), thread=True, name="poll-slow")

    def _fetch(self, sources) -> tuple[dict, bool | None, str]:
        snap, online, note = {}, None, ""
        for key, method, *args in sources:
            try:
                snap[key] = self.remote.call(method, *(args[0] if args else ()))
                online = True
            except Offline as e:
                return snap, False, str(e)
            except RemoteError as e:
                snap[key] = {"_error": str(e)}
                online = True
        return snap, online, note

    def _poll_fast(self) -> None:
        try:
            snap, online, note = self._fetch(BASE_SOURCES)
            self._post(self._apply, snap, online, note, True)
        finally:
            self._busy["fast"] = False

    def _poll_slow(self, due) -> None:
        try:
            snap, online, note = self._fetch([(k, m, a) for k, m, a, _e in due])
            self._post(self._apply, snap, online if online is False else None, note, False)
        finally:
            self._busy["slow"] = False

    def _apply(self, snap: dict, online, note: str, fast: bool) -> None:
        if online is not None:
            self._set_link(online, note)
        changed = []
        for key, value in snap.items():
            dumped = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
            if self._seen.get(key) != dumped:
                self._seen[key] = dumped
                self._state[key] = value
                self.pushes[key] += 1
                changed.append(key)
        if fast and self._full_render:
            self._full_render = False
            self.resync()
        elif changed:
            for pane in self._panes():
                pane.state_changed(changed)
        if changed and any(k == "app" for k in changed):
            self._update_top()

    def _set_link(self, online: bool, note: str = "") -> None:
        was = self.link
        self.link, self.link_note = online, note
        if online is False and was is not False:
            self.status(_tr('tui.textual_app.no_connection_to_chimera_showing_the_last_known'), error=True)
        elif online and was is False:
            self.status(_tr('tui.textual_app.connection_to_chimera_restored'))
            self._force = True
        self._update_top()

    def resync(self) -> None:
        """Перерисовать все вкладки по текущему состоянию (вернуть тумблеры на место после отказа)."""
        keys = list(self._state)
        for pane in self._panes():
            pane.state_changed(keys)

    # --- действия ------------------------------------------------------------------------------------------

    def act(self, title: str, method: str, *args, journal: str | None = None, after=None) -> None:
        """Действие в фоне: метод Api через канал, результат в строке состояния."""
        if self.link is not True:
            self.status(_tr('tui.textual_app.no_connection_to_chimera_was_not_performed', p0=title), error=True)
            self.resync()
            return
        self.status(f"{title}…")

        def work():
            try:
                result, error, offline = self.remote.call(method, *args), None, False
            except Offline as e:
                result, error, offline = None, str(e), True
            except RemoteError as e:
                result, error, offline = None, str(e), False
            self.remote.record(journal or method, error is None)
            self._post(self._act_done, title, result, error, offline, after)

        self.run_worker(work, thread=True, group="act")

    def _act_done(self, title, result, error, offline, after) -> None:
        if offline:
            self._set_link(False, error)
            self.status(_tr('tui.textual_app.no_connection_to_chimera_was_not_performed', p0=title), error=True)
        elif error:
            self.status(f"{title}: {error}", error=True)
        else:
            self.status(_tr('tui.textual_app.done', p0=title))
            if after:
                after(result)
        self._full_render = True
        if error:
            self.resync()
        self.refresh_now(force=True)

    def edit_list(self, name: str) -> None:
        """Правка lists/<имя>.txt во внешнем редакторе. Применение делает наблюдатель за файлами."""
        from modules import domains
        if not domains.NAME_RE.match(name):
            self.status(_tr('tui.textual_app.invalid_list_name', p0=name), error=True)
            return
        path = (self._lists_dir or domains.LISTS_DIR) / f"{name}.txt"
        try:
            try:
                with self.suspend():
                    self.editor(path)
            except SuspendNotSupported:   # драйвер не умеет отдавать терминал (тесты, некоторые оболочки)
                self.editor(path)
        except Exception as e:  # noqa: BLE001 — нет редактора, консоль не отдали: сообщаем, а не роняем интерфейс
            self.status(_tr('tui.textual_app.could_not_open_the_editor', p0=e), error=True)
            return
        self.status(_tr('tui.textual_app.list_changes_are_applied_automatically', p0=name))
        self.refresh_now(force=True)
