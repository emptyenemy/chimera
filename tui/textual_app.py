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
from collections import Counter

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import ContentSwitcher, OptionList, Static

from tui.navigation import HomeMenu, editing, move_focus
from tui.mutations import Change, StateWrites
from tui.editor import ListEditorScreen
from tui.console import ConsoleScreen
from tui.commandline import History

from tui import panes
from tui.remote import Offline, RemoteError
from tui.screens import ConfirmScreen, HelpScreen, PromptScreen
from tui.route_report import RouteReportScreen
from tui.autotune import AutotuneScreen

BASE_SOURCES = (("app", "app_info"), ("winws", "winws_state"), ("proxy", "proxy_state"),
                ("tg", "tg_state"), ("hosts_state", "hosts_state"), ("trial", "trial_state"),
                ("autotune", "autotune_state"))

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
#top { height: 1; padding: 0 1; color: $primary; text-style: bold; }
#top.offline { color: $error; }
#status { height: auto; min-height: 1; padding: 0 1; color: $foreground 80%; }
#status.error { color: $error; }
#trial-status { height: auto; padding: 0 1; color: $warning; }
ContentSwitcher { height: 1fr; }
#home { width: 76; max-width: 100%; height: 1fr; margin: 0 2; padding: 1 2; scrollbar-size: 0 0; }
#logo { height: auto; color: $primary; text-style: bold; margin-bottom: 1; }
#tagline { height: auto; margin-bottom: 1; }
#home-summary { height: auto; margin-bottom: 1; }
#menu { height: 9; }
#menu-description { height: auto; margin-top: 1; }
#keys { height: auto; padding: 0 1; color: $foreground 65%; }
Pane { height: 1fr; padding: 1 2; scrollbar-size: 0 0; }
.pane-summary { height: auto; margin-bottom: 1; color: $foreground 70%; }
.state-error { color: $error; }
OptionList { height: 1fr; border: none; padding: 0; background: transparent; scrollbar-size: 0 0; }
OptionList:focus { border: none; }
OptionList > .option-list--option-highlighted { background: $primary; color: $background; text-style: bold; }
RichLog { height: 1fr; scrollbar-size: 0 0; }
VerticalScroll { scrollbar-size: 0 0; }
.dim { color: $foreground 55%; }
ModalScreen { align: left top; padding: 2; }
.terminal-dialog { width: 80; max-width: 100%; height: auto; max-height: 100%; background: $background; }
.terminal-dialog Static { height: auto; }
.terminal-dialog OptionList { height: auto; max-height: 18; min-height: 1; margin-top: 1; }
.terminal-dialog Input { height: 1; border: none; padding: 0; margin-top: 1; background: transparent; }
.terminal-dialog Input:focus { border: none; }
.prompt-keys { height: auto; margin-top: 1; color: $foreground 60%; }
ListEditorScreen { padding: 1 2; }
ListEditorScreen Static { height: auto; }
#editor-title { color: $primary; text-style: bold; }
#list-text { height: 1fr; margin: 1 0; border: none; padding: 0; background: transparent; scrollbar-size: 0 0; }
#list-text:focus { border: none; }
#editor-keys { margin-top: 1; color: $foreground 60%; }
#route-title { height: auto; color: $primary; text-style: bold; }
#route-report { height: 1fr; margin-top: 1; }
#route-text { height: auto; }
#autotune-title { height: auto; color: $primary; text-style: bold; }
#autotune-report { height: auto; max-height: 60%; margin-top: 1; }
#autotune-text { height: auto; }
#autotune-actions { height: auto; max-height: 12; margin-top: 1; }
ConsoleScreen { padding: 1 2; }
ConsoleScreen Static { height: auto; }
#console-title { color: $primary; text-style: bold; margin-bottom: 1; }
#console-output { background: transparent; }
#console-status { margin-top: 1; color: $foreground 65%; }
#console-line { height: 1; margin-top: 1; }
#console-prefix { width: 2; color: $primary; }
#console-input { height: 1; border: none; padding: 0; background: transparent; }
#console-input:focus { border: none; }
#console-keys { margin-top: 1; color: $foreground 60%; }
"""


class ChimeraTui(App):
    TITLE = "Chimera"
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS
    BINDINGS = [
        Binding("q", "quit", _tr('tui.textual_app.quit')),
        Binding("ctrl+c", "quit", _tr('tui.textual_app.quit'), show=False, priority=True),
        Binding("colon", "console", "", show=False),
        Binding("ctrl+e", "explain", "", show=False),
        Binding("ctrl+f", "autotune", "", show=False),
        Binding("ctrl+t", "try_settings", _tr("tui.trial.try"), show=False),
        Binding("ctrl+k", "keep_trial", _tr("tui.trial.keep"), show=False),
        Binding("ctrl+r", "revert_trial", _tr("tui.trial.revert"), show=False),
        Binding("question_mark", "help", _tr('tui.textual_app.help')),
        Binding("escape", "back", _tr('tui.menu.back'), show=False),
        *[Binding(keys, f"navigate('{direction}')", "", show=False, priority=True)
          for keys, direction in (("up,w", "up"), ("down,s", "down"), ("left,a", "left"), ("right,d", "right"))],
        *[Binding(str(i), f"goto({i})", "", show=False) for i in range(1, len(SECTIONS) + 1)],
        *[Binding(f"ctrl+{i}", f"section({i})", "", show=False) for i in range(1, len(SECTIONS) + 1)],
    ]

    def run(self, **kwargs):
        kwargs["mouse"] = False
        return super().run(**kwargs)

    def __init__(self, remote, *, poll_interval: float = 1.0):
        super().__init__()
        self.remote = remote
        self.poll_interval = poll_interval
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
        self._writes = StateWrites()
        self._quit_requested = False
        self._quit_confirming = False
        self.list_drafts = {}
        self._console = None
        self.command_history = History()
        self.command_transcript = []
        self.command_draft = ""

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
        if action == "quit" and editing(self.screen.focused):
            return False
        if action == "console":
            return not self._blocked() and not editing(self.screen.focused)
        if action in ("explain", "autotune"):
            return not self._blocked() and not editing(self.screen.focused)
        if action == "navigate":
            return not editing(self.screen.focused)
        if action == "goto":
            return not self._blocked() and not editing(self.screen.focused)
        return True

    def open_section(self, sid: str) -> None:
        if self._blocked() or sid not in {sid for sid, _, _ in SECTIONS}:
            return
        self._content.current = sid
        self._keys.update(_tr("tui.menu.keys.log" if sid == "logs" else "tui.menu.keys.section"))
        self._update_top()
        self.call_after_refresh(self._focus_pane)
        self.refresh_now(force=True)

    def action_goto(self, n: int) -> None:
        if self._blocked() or editing(self.screen.focused):
            return
        if self.active_section == "home":
            self.action_section(n)
        else:
            pane = self._active_pane()
            if pane:
                pane.choose_number(n)

    def action_section(self, n: int) -> None:
        if not self._blocked() and 1 <= n <= len(SECTIONS):
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
        elif direction == "right" and not self._blocked() and self.active_section != "logs":
            self._active_pane().query_one(OptionList).action_select()
        elif direction == "left" and not self._blocked():
            self.action_back()
        else:
            move_focus(self.screen, direction)

    def action_quit(self) -> None:
        if self._console and (self._console.pending or self._writes.pending):
            self._console.exit_when_closed = True
            self._console.action_close()
            return
        if self._writes.pending:
            self._quit_requested = True
            self.status(_tr("tui.textual_app.finishing_writes"))
        elif self.list_drafts:
            if self._quit_confirming:
                return
            self._quit_confirming = True
            names = ', '.join(sorted(self.list_drafts))
            self.push_screen(ConfirmScreen(_tr('tui.editor.quit_confirm', names=names)), self._quit_answer)
        else:
            self.exit()

    def _quit_answer(self, discard):
        self._quit_confirming = self._quit_requested = False
        if discard:
            self.list_drafts.clear()
            self.exit()

    def action_console(self) -> None:
        if self._blocked() or self._quit_requested:
            return
        self._console = ConsoleScreen()
        self.push_screen(self._console, self._console_closed)

    def _console_closed(self, exit_requested):
        self._console = None
        if exit_requested:
            self.action_quit()

    def invalidate_command_state(self):
        keys = set(self._state) | set(self._writes.versions)
        keys.update(key for key, _method in BASE_SOURCES)
        keys.update(key for pane in self._panes() for key in pane.KEYS)
        for key in keys:
            self._writes.versions[key] += 1
        self._seen.clear()

    def action_explain(self) -> None:
        if self._blocked():
            return
        def entered(value):
            if value is not None and value.strip():
                self.push_screen(RouteReportScreen(value))
        self.push_screen(PromptScreen(_tr('tui.route.prompt')), entered)

    def action_autotune(self) -> None:
        if not self._blocked():
            self.push_screen(AutotuneScreen())

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

    def _fetch(self, sources) -> tuple[dict, bool | None, str, dict]:
        snap, online, note, versions = {}, None, "", {}
        for key, method, *args in sources:
            versions[key] = self._writes.versions[key]
            try:
                snap[key] = self.remote.call(method, *(args[0] if args else ()))
                online = True
            except Offline as e:
                return snap, False, str(e), versions
            except RemoteError as e:
                snap[key] = {"_error": str(e)}
                online = True
        return snap, online, note, versions

    def _poll_fast(self) -> None:
        try:
            snap, online, note, versions = self._fetch(BASE_SOURCES)
            self._post(self._apply, snap, online, note, True, versions)
        finally:
            self._busy["fast"] = False

    def _poll_slow(self, due) -> None:
        try:
            snap, online, note, versions = self._fetch([(k, m, a) for k, m, a, _e in due])
            self._post(self._apply, snap, online if online is False else None, note, False, versions)
        finally:
            self._busy["slow"] = False

    def _apply(self, snap: dict, online, note: str, fast: bool, versions: dict | None = None) -> None:
        if online is not None:
            self._set_link(online, note)
        changed = []
        for key, value in snap.items():
            version = (versions or {}).get(key, self._writes.versions[key])
            if not self._writes.accepts(key, version):
                continue
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

    def write_state(self, title, key, method, patch, arguments, *, journal=None, after=None, failed=None) -> bool:
        if self._quit_requested:
            self.status(_tr("tui.textual_app.finishing_writes"))
            return False
        if self.link is not True or self.data(key) is None:
            self.status(_tr("tui.textual_app.no_connection_to_chimera_was_not_performed", p0=title), error=True)
            if failed:
                failed()
            self.resync()
            return False
        if patch(self.data(key)) == self.data(key):
            return False
        first = self._writes.enqueue(key, self.data(key), Change(title, method, patch, arguments, journal, after, failed))
        self._show_write(key, self._writes.visible(key))
        if first:
            self._start_write(key)
        return True

    def _show_write(self, key, state) -> None:
        self._state[key] = state
        self._seen.pop(key, None)
        self._home.render_state()
        for pane in self._panes():
            pane.state_changed([key])

    def _start_write(self, key) -> None:
        change = self._writes.pending[key][0]
        self.act(change.title, change.method, *change.arguments(self._writes.target(key)), journal=change.journal,
                 after=lambda result: self._write_done(key, True, result),
                 failed=lambda: self._write_done(key, False, None), _queued=True)

    def _write_done(self, key, success, result) -> None:
        change = self._writes.pending[key][0]
        self._show_write(key, self._writes.finish(key, success))
        if not success:
            self._quit_requested = False
            if self._console:
                self._console.cancel_close()
        callback = change.after if success else change.failed
        if callback:
            callback(result) if success else callback()
        if key in self._writes.pending:
            self._start_write(key)
        elif self._quit_requested and not self._writes.pending:
            self._quit_requested = False
            self.action_quit()

    def act(self, title: str, method: str, *args, journal: str | None = None, after=None, failed=None, _queued=False, record=True) -> bool:
        """Действие в фоне: метод Api через канал, результат в строке состояния."""
        if self._quit_requested and not _queued:
            self.status(_tr("tui.textual_app.finishing_writes"))
            return False
        if self.link is not True:
            self.status(_tr('tui.textual_app.no_connection_to_chimera_was_not_performed', p0=title), error=True)
            if failed:
                failed()
            self.resync()
            return False
        self.status(f"{title}…")

        def work():
            try:
                result, error, offline = self.remote.call(method, *args), None, False
            except Offline as e:
                result, error, offline = None, str(e), True
            except Exception as e:  # noqa: BLE001 — очередь должна получить отказ при любой ошибке транспорта
                result, error, offline = None, str(e), False
            if record:
                self.remote.record(journal or method, error is None)
            self._post(self._act_done, title, result, error, offline, after, failed)

        self.run_worker(work, thread=True, group="act")
        return True

    def _act_done(self, title, result, error, offline, after, failed=None) -> None:
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
            if failed:
                failed()
            self.resync()
        self.refresh_now(force=True)

    def remember_list_draft(self, name, draft):
        was_dirty = name in self.list_drafts
        if draft is None:
            self.list_drafts.pop(name, None)
        else:
            self.list_drafts[name] = draft
        if self._content and was_dirty != (name in self.list_drafts):
            self._content.query_one('#lists', panes.ListsPane).render_state()

    def edit_list(self, name: str) -> None:
        from modules import domains
        if not isinstance(name, str) or not domains.NAME_RE.fullmatch(name):
            self.status(_tr('tui.textual_app.invalid_list_name', p0=name), error=True)
            return
        self.push_screen(ListEditorScreen(name))
