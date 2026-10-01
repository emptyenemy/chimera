"""Полноэкранный TUI на Textual: клиент работающей Chimera (`chimera tui`).

Приложение не создаёт свой Api и не владеет процессами: все данные и действия идут через
tui/remote.py теми же методами, что у командной строки. Выход из TUI (q) Chimera не
останавливает.

Живое состояние — фоновые воркеры Textual раз в ~1 с (в потоках, интерфейс не блокируется):
  быстрый  — состояние модулей для «Обзора» и меню;
  ленивый  — тяжёлое (списки, hosts, DNS, логи, настройки) только для открытого раздела.
В разделы состояние попадает лишь при изменении. Нет связи — в шапке «нет связи с Chimera»,
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
from textual.widgets import ContentSwitcher, DataTable, OptionList, Static

from tui.navigation import HomeMenu, editing, move_focus

from tui import panes
from tui.remote import Offline, RemoteError
from tui.screens import ConfirmScreen, HelpScreen

BASE_SOURCES = (("app", "app_info"), ("winws", "winws_state"), ("proxy", "proxy_state"),
                ("tg", "tg_state"), ("hosts_state", "hosts_state"), ("trial", "trial_state"))

SECTIONS = (("overview", _tr('tui.textual_app.overview'), panes.OverviewPane), ("strategies", _tr('tui.textual_app.strategies'), panes.StrategiesPane),
        ("lists", _tr('tui.textual_app.lists'), panes.ListsPane), ("proxy", _tr('tui.textual_app.proxy'), panes.ProxyPane),
        ("hosts", "Hosts", panes.HostsPane), ("dns", "DNS", panes.DnsPane),
        ("tg", "Telegram", panes.TgPane), ("logs", _tr('tui.textual_app.logs'), panes.LogsPane),
        ("settings", _tr('tui.textual_app.settings'), panes.SettingsPane))

# Один акцент для выбора и фокуса; состояния модулей сохраняют свои цвета.
THEME = Theme(name="chimera", primary="#a78bfa", secondary="#78718c", accent="#a78bfa", warning="#e3bb6b",
              error="#e5949e", success="#91c9a0", foreground="#e3e0eb", background="#111015",
              surface="#19171f", panel="#24212d", dark=True)

CSS = """
Screen { background: $background; }
#top { height: 1; padding: 0 1; background: $panel; color: $foreground; }
#top.offline { color: $error; }
#status { height: 1; padding: 0 1; color: $foreground 80%; }
#status.error { color: $error; }
#trial-status { height: auto; padding: 0 1; color: $primary; background: $surface; }
ContentSwitcher { height: 1fr; }
#home { width: 72; max-width: 100%; height: 1fr; margin: 0 2; padding: 1 2; }
#logo { height: auto; color: $primary; text-style: bold; margin-bottom: 1; }
#tagline { height: auto; margin-bottom: 1; }
#home-summary { height: auto; margin-bottom: 1; }
#menu { height: 11; border: round $panel; background: $surface; padding: 0 1; }
#menu:focus { border: round $primary; }
#menu-description { height: auto; margin-top: 1; }
#keys { height: auto; padding: 0 1; background: $panel; color: $foreground 70%; }
Pane { padding: 1 2; overflow-y: auto; }
Button:focus { text-style: bold; }
DataTable:focus { border: round $primary; }
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
        Binding("ctrl+t", "try_settings", _tr("tui.trial.try"), show=False),
        Binding("ctrl+k", "keep_trial", _tr("tui.trial.keep"), show=False),
        Binding("ctrl+r", "revert_trial", _tr("tui.trial.revert"), show=False),
        Binding("question_mark", "help", _tr('tui.textual_app.help')),
        Binding("escape", "back", _tr('tui.menu.back'), show=False),
        *[Binding(keys, f"navigate('{direction}')", "", show=False, priority=True)
          for keys, direction in (("up,w", "up"), ("down,s", "down"), ("left,a", "left"), ("right,d", "right"))],
        *[Binding(str(i), f"goto({i})", SECTIONS[i - 1][1], show=False) for i in range(1, len(SECTIONS) + 1)],
    ]

    def run(self, **kwargs):
        kwargs["mouse"] = False
        return super().run(**kwargs)

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
        self._content = self._top = self._status = self._keys = self._home = self._trial_status = None
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
    def active_section(self) -> str:
        return self._content.current

    def _panes(self) -> list:
        return list(self._content.query(panes.Pane))

    def _active_pane(self):
        return next((p for p in self._panes() if p.id == self.active_section), None)

    # --- вид ---------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("Chimera", id="top", markup=False)
        with ContentSwitcher(initial="home", id="content"):
            yield HomeMenu(SECTIONS)
            for sid, _, cls in SECTIONS:
                yield cls(id=sid)
        yield Static("", id="trial-status", markup=False)
        yield Static("", id="status", markup=False)
        yield Static(_tr("tui.menu.keys.home"), id="keys", markup=False)

    def on_mount(self) -> None:
        # ссылки на постоянные виджеты: поверх разделов бывает окно (подтверждение, подсказка), и
        # query_one() у приложения ищет только на верхнем экране
        self._content = self.query_one(ContentSwitcher)
        self._home = self.query_one(HomeMenu)
        self._keys = self.query_one('#keys', Static)
        self._top = self.query_one("#top", Static)
        self._status = self.query_one("#status", Static)
        self._trial_status = self.query_one("#trial-status", Static)
        self._trial_status.display = False
        self.register_theme(THEME)
        self.theme = "chimera"
        self._update_top()
        self.set_interval(self.poll_interval, self._on_tick)
        self.run_worker(self._startup, thread=True, name="startup")
        self._home.compact(self.size.height)
        self.query_one('#menu', OptionList).focus()

    def on_resize(self, event) -> None:
        if self._home is not None:
            self._home.compact(event.size.height)

    def _update_top(self) -> None:
        app = self._state.get("app") or {}
        ver = f" {app['version']}" if app.get("version") else ""
        note = {True: _tr('tui.textual_app.connected_to_chimera'), None: _tr('tui.textual_app.connecting_to_chimera')}.get(self.link)
        if self.link is False:
            note = _tr('tui.textual_app.no_connection_to_chimera')
            if self.link_note and self.link_note != note:
                note += f" ({self.link_note})"
        title = next((title for sid, title, _ in SECTIONS if sid == self.active_section), _tr("tui.menu.title"))
        self._top.update(f"Chimera{ver} / {title} · {note}")
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

    def check_action(self, action: str, parameters: tuple) -> bool:
        if action == "navigate":
            return not editing(self.screen.focused)
        if action == "goto":
            return not self._blocked() and not editing(self.screen.focused)
        return True

    def open_section(self, sid: str) -> None:
        if self._blocked() or sid not in {sid for sid, _, _ in SECTIONS}:
            return
        self._content.current = sid
        self._keys.update(_tr("tui.menu.keys.section"))
        self._update_top()
        self.call_after_refresh(self._focus_pane)
        self.refresh_now(force=True)

    def action_goto(self, n: int) -> None:
        if 1 <= n <= len(SECTIONS):
            self.open_section(SECTIONS[n - 1][0])

    def action_back(self) -> None:
        if self._blocked():
            return
        previous = self.active_section
        self._content.current = "home"
        menu = self._home.query_one(OptionList)
        if previous != "home":
            menu.highlighted = next(i for i, (sid, _, _) in enumerate(SECTIONS) if sid == previous)
        self._keys.update(_tr("tui.menu.keys.home"))
        self._update_top()
        menu.focus()

    def action_navigate(self, direction: str) -> None:
        if not self._blocked() and self.active_section == "home":
            menu = self._home.query_one(OptionList)
            if direction in ("up", "down"):
                menu.highlighted = ((menu.highlighted or 0) + (1 if direction == "down" else -1)) % len(SECTIONS)
            elif direction == "right":
                menu.action_select()
        elif not self._blocked() and direction == "left" and not (
            isinstance(self.screen.focused, DataTable) and self.screen.focused.cursor_type == "cell"
        ):
            self.action_back()
        else:
            move_focus(self.screen, direction)

    def action_help(self) -> None:
        if not self._blocked():
            self.push_screen(HelpScreen())

    def action_try_settings(self) -> None:
        if self._blocked():
            return
        pane = self._active_pane()
        target = pane.trial_target() if pane is not None else None
        if not target:
            self.status(_tr("tui.trial.select"))
            return
        kind, value = target
        self.confirm(_tr("tui.trial.confirm", target=value),
                     lambda: self.act(_tr("tui.trial.try"), "trial_start", kind, value, 60, None))

    def _finish_trial(self, keep):
        if self._blocked():
            return
        active = (self.data("trial") or {}).get("active") or {}
        if not active.get("id"):
            self.status(_tr("tui.trial.none"))
            return
        self.act(_tr("tui.trial.keep") if keep else _tr("tui.trial.revert"),
                 "trial_confirm" if keep else "trial_revert", active["id"])

    def action_keep_trial(self):
        self._finish_trial(True)

    def action_revert_trial(self):
        self._finish_trial(False)

    def _render_trial(self):
        active = (self.data("trial") or {}).get("active")
        self._trial_status.display = bool(active)
        if not active:
            return
        if active.get("error"):
            self._trial_status.update(_tr(active["error"]))
        else:
            self._trial_status.update(_tr("tui.trial.status", target=active.get("target", ""), seconds=active.get("seconds_left", 0)))

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
        def deliver():
            # Ответ уже в очереди, но экран может быть разобран при закрытии.
            if self.is_running:
                fn(*args)

        try:
            self.call_from_thread(deliver)
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
        if changed:
            self._home.render_state()
            if "trial" in changed:
                self._render_trial()
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
        """Перерисовать все разделы по текущему состоянию (вернуть тумблеры на место после отказа)."""
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
