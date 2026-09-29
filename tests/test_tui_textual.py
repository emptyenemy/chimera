"""Полноэкранный TUI (tui/textual_app.py) на Textual Pilot в headless-режиме.

Настоящая Chimera и окно не запускаются: вместо канала управления — FakeRemote с теми же
методами Api, что в таблице команд, и записью вызовов. Реальные потоки только фоновые
воркеры Textual, которые ходят в FakeRemote.
"""

import asyncio
import time

from textual.widgets import Button, DataTable, RadioButton, RichLog, Static, Switch

from modules import control
from tui.remote import Offline, RemoteError
from tui.screens import ConfirmScreen, HelpScreen, ListPicker
from tui.textual_app import TABS, ChimeraTui

SECRET = "ddaa11bb22cc33dd44ee55ff66aa77bb88"


class FakeRemote:
    """Поддельная Chimera: состояние в памяти, действия меняют его как настоящие."""

    def __init__(self):
        self.calls = []
        self.journal = []
        self.offline = False
        self.errors = {}
        self.ensure_calls = 0
        self.winws = {"running": False, "current": None, "last_strategy": None, "external": False, "error": None,
                      "version": "1.0.5.2",
                      "strategies": [{"id": "general", "name": "general", "desc": "обычная"},
                                     {"id": "discord", "name": "discord", "desc": "для Discord"}]}
        self.proxy = {"running": False, "mode": "pac", "external": False, "apps": ["Discord.exe"], "domains": 5, "ips": 1,
                      "core": {"present": True, "version": "1.12"}, "error": None}
        self.tg = {"running": False, "host": "127.0.0.1", "port": 1443, "autostart": False, "version": "1.10",
                   "link": "tg://…(скрыто)", "error": None}
        self.hosts = {"enabled": True, "applied": True, "count": 12, "assignments": {"comss": ["discord"]}}
        self.lists = [{"name": "discord", "count": 10, "winws": True, "proxy": False, "hosts": True},
                      {"name": "youtube", "count": 20, "winws": False, "proxy": False, "hosts": False}]
        self.dns = {"adapters": [{"index": 7, "name": "Ethernet", "status": "Up", "dns": ["1.1.1.1"]}],
                    "providers": [{"id": "cf", "name": "Cloudflare", "servers": ["1.1.1.1"]}], "trial": None, "trials": []}
        self.config = {"interface": "ui", "ui_backend": "pyside6"}
        self.log = "строка лога 1\nстрока лога 2\n"

    # --- Remote -------------------------------------------------------------------------------

    def ensure_running(self, progress=None):
        self.ensure_calls += 1
        return False

    def record(self, label, ok):
        self.journal.append((label, ok))

    def methods(self):
        return [c[0] for c in self.calls]

    def call(self, method, *args):
        self.calls.append((method, args))
        if self.offline:
            raise Offline("нет связи с Chimera")
        if method in self.errors:
            raise RemoteError(self.errors[method])
        return getattr(self, "m_" + method)(*args)

    def m_app_info(self):
        return {"admin": True, "version": "1.2.3", "service_running": False, "frozen": False}

    def m_winws_state(self):
        return dict(self.winws)

    def m_proxy_state(self):
        return dict(self.proxy)

    def m_tg_state(self):
        return dict(self.tg)

    def m_hosts_state(self):
        return dict(self.hosts)

    def m_winws_start(self, sid):
        self.winws.update(running=True, current=sid, last_strategy=sid)
        return {}

    def m_winws_stop(self):
        self.winws.update(running=False, current=None)
        return {}

    def m_proxy_start(self):
        self.proxy["running"] = True
        return {}

    def m_proxy_stop(self):
        self.proxy["running"] = False
        return {}

    def m_proxy_set_mode(self, mode):
        self.proxy["mode"] = mode
        return {}

    def m_proxy_set_apps(self, names):
        self.proxy["apps"] = list(names)
        return {}

    def m_tg_start(self):
        self.tg["running"] = True
        return {}

    def m_tg_stop(self):
        self.tg["running"] = False
        return {}

    def m_tg_stats(self):
        return {"connections": 3}

    def m_hosts_set_enabled(self, value):
        self.hosts["enabled"] = value
        return {}

    def m_hosts_overview(self):
        return {"providers": [{"id": "comss", "name": "Comss", "type": "dns"}, {"id": "xbox", "name": "Xbox", "type": "static"}],
                "lists": [{"name": "discord", "count": 10}, {"name": "youtube", "count": 20}], "state": self.hosts}

    def m_hosts_set_assignments(self, mapping):
        self.hosts["assignments"] = mapping
        return {}

    def m_lists_all(self):
        return [dict(i) for i in self.lists]

    def m_winws_set_lists(self, names):
        for i in self.lists:
            i["winws"] = i["name"] in names
        return {}

    def m_proxy_set_lists(self, names):
        for i in self.lists:
            i["proxy"] = i["name"] in names
        return {}

    def m_dns_state(self):
        return {**self.dns, "trials": list(self.dns["trials"])}

    def m_dns_set_trial(self, adapter, provider, seconds):
        self.dns["trials"] = [{"adapter": adapter, "provider": provider, "seconds_left": seconds}]
        return {}

    def m_dns_trial_confirm(self, adapter=None):
        self.dns["trials"] = []
        return {}

    def m_dns_trial_revert(self, adapter=None):
        self.dns["trials"] = []
        return {}

    def m_dns_reset(self, adapter):
        return {}

    def m_panic_all(self):
        return {"steps": [{"step": "winws", "ok": True}, {"step": "hosts", "ok": False, "error": "нужны права"}], "failed": 1}

    def m_winws_log(self, offset=0):
        return {"offset": len(self.log), "data": self.log[offset:], "reset": offset == 0}

    def m_proxy_log(self, offset=0):
        return {"offset": 14, "data": "proxy: строка\n" if offset == 0 else "", "reset": offset == 0}

    def m_tg_log(self, offset=0):
        return {"offset": 0, "data": "", "reset": False}

    def m_config_read(self):
        return dict(self.config)

    def m_config_set(self, key, value):
        self.config[key] = value
        return dict(self.config)


def drive(scenario, remote=None, **kw):
    """Запускает приложение в headless и отдаёт сценарию (app, pilot, remote)."""
    remote = remote or FakeRemote()

    async def go():
        app = ChimeraTui(remote, poll_interval=0.05, **kw)
        async with app.run_test(size=(130, 42)) as pilot:
            await scenario(app, pilot, remote)

    asyncio.run(go())
    # TUI зовёт только то, что канал управления разрешает командной строке
    assert set(remote.methods()) <= control.ALLOWED_METHODS, set(remote.methods()) - control.ALLOWED_METHODS
    return remote


async def until(pilot, cond, timeout=4.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await pilot.pause(0.02)
        if cond():
            return
    raise AssertionError("условие не выполнилось за отведённое время")


async def online(pilot, app):
    await until(pilot, lambda: app.link is True and app.data("winws") is not None)
    await pilot.pause(0.1)      # начальная расстановка фокуса на вкладке уже отработала


def text(app, wid):
    return str(app.query_one(wid, Static).render())


# --- вкладки ------------------------------------------------------------------------------------

def test_nine_tabs_with_numbers():
    assert [t[0] for t in TABS] == ["overview", "strategies", "lists", "proxy", "hosts", "dns", "tg", "logs", "settings"]


def test_digits_tab_and_shift_tab_switch_tabs():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        assert app.active_tab == "overview"
        await pilot.press("3")
        assert app.active_tab == "lists"
        await pilot.press("tab")
        assert app.active_tab == "proxy"
        await pilot.press("shift+tab", "shift+tab")
        assert app.active_tab == "strategies"
        await pilot.press("9")
        assert app.active_tab == "settings"
        await pilot.press("tab")
        assert app.active_tab == "overview"    # по кругу
    drive(scenario)


def test_help_opens_and_closes_and_blocks_digits():
    async def scenario(app, pilot, remote):
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("5")
        assert app.active_tab == "overview"    # под подсказкой вкладки не переключаются
        await pilot.press("escape")
        assert not isinstance(app.screen, HelpScreen)
    drive(scenario)


def test_q_quits_without_stopping_chimera():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("q")
        await pilot.pause(0.05)
        assert not app.is_running or app._exit
    remote = drive(scenario)
    assert not [m for m in remote.methods() if m.endswith("stop") or m == "panic_all"]


def test_startup_asks_remote_to_bring_chimera_up():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
    assert drive(scenario).ensure_calls == 1


# --- живое состояние -----------------------------------------------------------------------------

def test_state_is_pushed_only_when_it_changes():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.pause(0.4)                 # с десяток опросов подряд
        assert len(remote.calls) > 15
        assert app.pushes["winws"] == 1 and app.pushes["app"] == 1
        remote.winws["running"] = True
        await until(pilot, lambda: app.pushes["winws"] == 2)
    drive(scenario)


def test_lazy_sources_are_polled_only_while_their_tab_is_open():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.pause(0.2)
        assert "lists_all" not in remote.methods() and "dns_state" not in remote.methods()
        await pilot.press("3")
        await until(pilot, lambda: "lists_all" in remote.methods())
        await pilot.press("1")
        await pilot.pause(0.1)
        n = remote.methods().count("lists_all")
        await pilot.pause(0.4)
        assert remote.methods().count("lists_all") == n
    drive(scenario)


def test_no_connection_shows_status_and_reconnects_by_itself():
    async def scenario(app, pilot, remote):
        remote.offline = True
        await until(pilot, lambda: app.link is False)
        assert "нет связи с Chimera" in text(app, "#top")
        assert "Нет связи с Chimera" in app.status_text
        remote.offline = False
        await until(pilot, lambda: app.link is True)
        assert "восстановлена" in app.status_text
        assert "связь с Chimera есть" in text(app, "#top")
    drive(scenario)


def test_actions_are_refused_without_connection():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        remote.offline = True
        await until(pilot, lambda: app.link is False)
        before = len(remote.calls)
        app.query_one("#sw-tg", Switch).focus()
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert "не выполнено" in app.status_text
        assert "tg_start" not in remote.methods()
        assert not app.query_one("#sw-tg", Switch).value     # тумблер вернулся на место
        assert len(remote.calls) >= before
    drive(scenario)


def test_connection_lost_during_action_is_reported():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        def dies():
            remote.offline = True
            raise Offline("нет связи с Chimera")
        remote.m_tg_start = dies
        app.act("Запуск Telegram-прокси", "tg_start", journal="tg start")
        await until(pilot, lambda: app.link is False)
        assert "не выполнено" in app.status_text
    drive(scenario)


# --- обзор -----------------------------------------------------------------------------------------

def test_overview_shows_module_states_and_toggles_work():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        assert "остановлен" in text(app, "#st-tg")
        assert "1.2.3" in text(app, "#ov-app")
        app.query_one("#sw-tg", Switch).focus()
        await pilot.press("space")
        await until(pilot, lambda: ("tg_start", ()) in remote.calls)
        await until(pilot, lambda: "работает" in text(app, "#st-tg"))
        assert app.query_one("#sw-tg", Switch).value is True
        assert ("tg start", True) in remote.journal
        await pilot.press("space")
        await until(pilot, lambda: ("tg_stop", ()) in remote.calls)
    drive(scenario)


def test_winws_switch_needs_a_chosen_strategy_first():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        app.query_one("#sw-winws", Switch).focus()
        await pilot.press("space")
        await pilot.pause(0.1)
        assert "winws_start" not in remote.methods()
        assert "Стратегии" in app.status_text
        assert not app.query_one("#sw-winws", Switch).value
        remote.winws["last_strategy"] = "discord"
        await until(pilot, lambda: (app.data("winws") or {}).get("last_strategy") == "discord")
        await pilot.press("space")
        await until(pilot, lambda: ("winws_start", ("discord",)) in remote.calls)
    drive(scenario)


def test_hosts_switch_on_overview_turns_hosts_off():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        app.query_one("#sw-hosts_state", Switch).focus()
        await pilot.press("space")
        await until(pilot, lambda: ("hosts_set_enabled", (False,)) in remote.calls)
    drive(scenario)


def test_remote_error_is_shown_and_switch_returns():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        remote.errors["proxy_start"] = "Нужны права администратора"
        app.query_one("#sw-proxy", Switch).focus()
        await pilot.press("space")
        await until(pilot, lambda: "Нужны права администратора" in app.status_text)
        await until(pilot, lambda: not app.query_one("#sw-proxy", Switch).value)
        assert ("proxy start", False) in remote.journal
    drive(scenario)


def test_panic_asks_for_confirmation():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.click("#panic")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("n")
        await pilot.pause(0.1)
        assert "panic_all" not in remote.methods()
        await pilot.click("#panic")
        await pilot.press("y")
        await until(pilot, lambda: "panic_all" in remote.methods())
        await until(pilot, lambda: "hosts (нужны права)" in app.status_text)
    drive(scenario)


# --- стратегии ------------------------------------------------------------------------------------------

def test_strategies_search_and_enter_starts():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("2")
        table = app.query_one("#st-table", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        await pilot.press("slash", "d", "i", "s")
        await until(pilot, lambda: table.row_count == 1)
        await pilot.press("enter")      # из поиска в таблицу
        await pilot.press("enter")      # выбрать
        await until(pilot, lambda: ("winws_start", ("discord",)) in remote.calls)
        await until(pilot, lambda: "стратегия discord" in text(app, "#st-head"))
        await pilot.press("x")
        await until(pilot, lambda: "winws_stop" in remote.methods())
    drive(scenario)


# --- списки --------------------------------------------------------------------------------------------------

def test_lists_checkboxes_toggle_winws_and_proxy_and_hosts_is_readonly():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("3")
        table = app.query_one("#ls-table", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        assert table.get_row_at(0)[2:] == ["☑", "☐", "☑"]
        await pilot.press("down", "right", "right", "space")          # youtube -> winws
        await until(pilot, lambda: ("winws_set_lists", (["discord", "youtube"],)) in remote.calls)
        await pilot.press("right", "enter")                           # youtube -> прокси
        await until(pilot, lambda: ("proxy_set_lists", (["youtube"],)) in remote.calls)
        await pilot.press("right", "space")
        assert "Hosts" in app.status_text
        assert "hosts_set_assignments" not in remote.methods()
    drive(scenario)


def test_lists_e_opens_external_editor_and_says_changes_apply_automatically(tmp_path):
    opened = []

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("3")
        table = app.query_one("#ls-table", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        await pilot.press("down", "e")
        await until(pilot, lambda: bool(opened))
        assert opened == [tmp_path / "youtube.txt"]
        assert "применяются автоматически" in app.status_text
        assert not [m for m in remote.methods() if m.startswith("lists_save")]   # применение — дело наблюдателя за файлами
    drive(scenario, editor=opened.append, lists_dir=tmp_path)


# --- прокси -----------------------------------------------------------------------------------------------------

def test_proxy_tab_mode_start_and_apps():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("4")
        await until(pilot, lambda: app.query_one("#mode-pac", RadioButton).value)
        await pilot.click("#mode-tun")
        await until(pilot, lambda: ("proxy_set_mode", ("tun",)) in remote.calls)
        await pilot.click("#px-toggle")
        await until(pilot, lambda: "proxy_start" in remote.methods())
        await until(pilot, lambda: str(app.query_one("#px-toggle", Button).label) == "Остановить")
        app.query_one("#px-add").focus()
        await pilot.press(*"x.exe", "enter")
        await until(pilot, lambda: ("proxy_set_apps", (["Discord.exe", "x.exe"],)) in remote.calls)
        app.query_one("#px-apps", DataTable).focus()
        await pilot.press("delete")
        await until(pilot, lambda: ("proxy_set_apps", (["x.exe"],)) in remote.calls)
    drive(scenario)


# --- hosts ------------------------------------------------------------------------------------------------------------

def test_hosts_switch_and_provider_lists_picker():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("5")
        table = app.query_one("#hs-table", DataTable)
        await until(pilot, lambda: table.row_count == 2)
        assert table.get_row_at(0)[2] == "discord"
        table.focus()
        await pilot.press("down", "enter")        # xbox: выбрать списки
        assert isinstance(app.screen, ListPicker)
        await pilot.press("space")                # отметить первый список
        await pilot.click("#ok")
        await until(pilot, lambda: any(c[0] == "hosts_set_assignments" for c in remote.calls))
        assert ("hosts_set_assignments", ({"comss": ["discord"], "xbox": ["discord"]},)) in remote.calls
        app.query_one("#hs-enabled", Switch).focus()
        await pilot.press("space")
        await until(pilot, lambda: ("hosts_set_enabled", (False,)) in remote.calls)
    drive(scenario)


# --- DNS -----------------------------------------------------------------------------------------------------------------------

def test_dns_trial_apply_keep_and_reset():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("6")
        adapters = app.query_one("#dn-adapters", DataTable)
        await until(pilot, lambda: adapters.row_count == 1)
        await pilot.press("f", "enter")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await until(pilot, lambda: ("dns_set_trial", (7, "cf", 15)) in remote.calls)
        await until(pilot, lambda: "Проба DNS" in text(app, "#dn-trial"))
        await pilot.click("#dn-keep")
        await until(pilot, lambda: "dns_trial_confirm" in remote.methods())
        adapters.focus()
        await pilot.press("r")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("n")
        await pilot.pause(0.1)
        assert "dns_reset" not in remote.methods()
        await pilot.press("r", "y")
        await until(pilot, lambda: ("dns_reset", (7,)) in remote.calls)
    drive(scenario)


# --- Telegram ---------------------------------------------------------------------------------------------------------------------

def test_telegram_link_is_masked_and_start_works():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        remote.tg["link"] = f"tg://proxy?server=127.0.0.1&port=1443&secret={SECRET}"   # так бы вышло без маски
        await pilot.press("7")
        await until(pilot, lambda: "secret=…(скрыто)" in text(app, "#tg-info"))
        shown = " ".join(str(w.render()) for w in app.query(Static))
        assert SECRET not in shown
        await pilot.click("#tg-toggle")
        await until(pilot, lambda: "tg_start" in remote.methods())
        await until(pilot, lambda: "tg_stats" in remote.methods())
    drive(scenario)


# --- логи и настройки ---------------------------------------------------------------------------------------------------------------

def test_logs_tail_and_file_choice():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("8")
        view = app.query_one("#lg-view", RichLog)
        await until(pilot, lambda: len(view.lines) == 2)
        remote.log += "строка лога 3\n"
        await until(pilot, lambda: len(view.lines) == 3)
        await pilot.click("#log-proxy")
        await until(pilot, lambda: ("proxy_log", (0,)) in remote.calls)
        await until(pilot, lambda: len(view.lines) == 1)
    drive(scenario)


def test_settings_theme_written_through_config_set_and_language_hidden():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("9")
        await until(pilot, lambda: app.query_one("#theme-system", RadioButton).value)
        assert app.query_one("#se-lang").has_class("hidden")
        await pilot.click("#theme-dark")
        await until(pilot, lambda: ("config_set", ("theme", "dark")) in remote.calls)
        assert ("config set theme dark", True) in remote.journal
    drive(scenario)


def test_language_shown_only_when_key_exists():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("9")
        await until(pilot, lambda: not app.query_one("#se-lang").has_class("hidden"))
        assert "ru" in text(app, "#se-lang")
    remote = FakeRemote()
    remote.config["language"] = "ru"
    drive(scenario, remote)


def test_screenshot_exports_svg():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        assert app.export_screenshot().lstrip().startswith("<svg")
    drive(scenario)
