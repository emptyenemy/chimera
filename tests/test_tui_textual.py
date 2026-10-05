"""Полноэкранный TUI (tui/textual_app.py) на Textual Pilot в headless-режиме.

Настоящая Chimera и окно не запускаются: вместо канала управления — FakeRemote с теми же
методами Api, что в таблице команд, и записью вызовов. Реальные потоки только фоновые
воркеры Textual, которые ходят в FakeRemote.
"""

import asyncio
import time

from textual.widgets import Input, OptionList, Button, RichLog, Static, TextArea

from tui.editor import ListEditorScreen

from modules import control
from tui.remote import Offline, RemoteError
from tui.screens import ConfirmScreen, HelpScreen, ListPicker, MenuScreen, PromptScreen
from tui.textual_app import SECTIONS, ChimeraTui

SECRET = "ddaa11bb22cc33dd44ee55ff66aa77bb88"


def test_late_worker_callback_is_ignored_after_screen_shutdown(monkeypatch):
    from unittest.mock import Mock
    app = ChimeraTui(FakeRemote())
    monkeypatch.setattr(app, "call_from_thread", lambda callback, *args: callback(*args))
    update = Mock()
    app._post(update, "late response")
    update.assert_not_called()
    app._running = True
    try:
        app._post(update, "live response")
        update.assert_called_once_with("live response")
    finally:
        app._running = False


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
        self.list_text = {'discord': '# Discord\ndiscord.com\n', 'youtube': 'youtube.com\n'}
        self.dns = {"adapters": [{"index": 7, "name": "Ethernet", "status": "Up", "dns": ["1.1.1.1"]}],
                    "providers": [{"id": "cf", "name": "Cloudflare", "servers": ["1.1.1.1"]}], "trial": None, "trials": []}
        self.config = {"interface": "ui", "ui_backend": "pyside6"}
        self.trial = {"active": None, "last": None}
        self.autotune = {"active": None, "last": None}
        self.log ="строка лога 1\nстрока лога 2\n"

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

    def m_tg_set_advanced(self, options):
        self.tg.update(options)
        return dict(self.tg)

    def m_tg_stats(self):
        return {"connections": 3}

    def m_hosts_set_enabled(self, value):
        self.hosts["enabled"] = value
        return {}

    def m_hosts_overview(self):
        return {"providers": [{"id": "comss", "name": "Comss", "type": "dns"}, {"id": "malw", "name": "Malw", "type": "dns"},
                                 {"id": "flowseal", "name": "Flowseal", "type": "static"}],
                "lists": [{"name": "discord", "count": 10}, {"name": "youtube", "count": 20}], "state": self.hosts}

    def m_hosts_set_assignments(self, mapping):
        self.hosts["assignments"] = mapping
        return {}

    def m_lists_all(self):
        return [dict(i) for i in self.lists]

    def m_lists_read(self, name):
        return self.list_text[name]

    def m_lists_save(self, name, content):
        self.list_text[name] = content.replace('\r\n', '\n').rstrip('\n') + '\n'
        count = sum(bool(line.split('#', 1)[0].strip()) for line in content.splitlines())
        for item in self.lists:
            if item['name'] == name:
                item['count'] = count
        return {'name': name, 'count': count, 'apply_errors': []}

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

    def m_trial_state(self):
        return self.trial

    def m_trial_start(self, kind, target, seconds, domains):
        self.trial = {"active": {"id": "trial-1", "kind": kind, "target": target,
                                 "phase": "pending", "seconds_left": seconds, "checks_done": True}, "last": None}
        return self.trial

    def m_trial_confirm(self, trial_id):
        self.trial = {"active": None, "last": {"id": trial_id, "phase": "confirmed"}}
        return self.trial

    def m_trial_revert(self, trial_id):
        self.trial = {"active": None, "last": {"id": trial_id, "phase": "reverted"}}
        return self.trial

    def m_autotune_state(self):
        return self.autotune

    def m_autotune_catalog(self):
        return [{"name": "youtube", "targets": ["youtube.com"]}, {"name": "discord", "targets": ["discord.com"]}]

    def m_autotune_diagnose(self, services=None):
        return {"offline": False, "services": [{"name": "youtube", "ok": False, "reasons": ["dpi"], "covered": 0, "total": 1},
                                               {"name": "discord", "ok": True}]}

    def m_autotune_start(self, services=None, mode="fast"):
        names = services or ["youtube", "discord"]
        rows = [{"name": n, "before": {"ok": n != "youtube", "reasons": ["dpi"] if n == "youtube" else []},
                 "after": {"ok": True}, "fix": {"kind": "strategy", "id": "alt"} if n == "youtube" else None} for n in names]
        self.autotune = {"active": {"id": "s1", "phase": "done", "mode": mode, "trigger": "user", "services": names,
                                    "report": {"services": rows, "fixes": {}}}, "last": None}
        return self.autotune

    def m_autotune_keep(self):
        self.autotune = {"active": None, "last": {**self.autotune["active"], "phase": "kept"}}
        return self.autotune

    def m_autotune_revert(self):
        self.autotune = {"active": None, "last": {**self.autotune["active"], "phase": "reverted"}}
        return self.autotune

    def m_autotune_cancel(self):
        self.autotune["active"]["cancelling"] = True
        return self.autotune

    def m_autotune_share(self):
        return {"title": "t", "text": "отчёт", "url": "https://github.com/emptyenemy/chimera/discussions/new?x", "form": "f"}

    def m_config_verified(self):
        return {"backup": None, "error": None}

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



def test_classic_menu_has_no_window_controls_or_visible_scrollbars():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        for number, (name, _, _) in enumerate(SECTIONS, 1):
            await pilot.press(f"ctrl+{number}")
            await pilot.pause(0.05)
            assert app.active_section == name
            assert not list(app.query("Button, Switch, RadioSet, DataTable, TabbedContent"))
            pane = app.query_one('#' + name)
            assert pane.styles.scrollbar_size_vertical == 0
            for view in pane.query("OptionList, RichLog"):
                assert view.styles.scrollbar_size_vertical == 0
                assert view.styles.scrollbar_size_horizontal == 0
        assert app.export_screenshot().lstrip().startswith("<svg")
    drive(scenario)


def test_home_numbers_and_arrows_open_sections_and_section_numbers_choose_actions():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("s", "down", "w", "d")
        assert app.active_section == "strategies"
        await pilot.press("escape", "4")
        assert app.active_section == "proxy"
        await pilot.press("2")
        assert isinstance(app.screen, MenuScreen)
        await pilot.press("3")
        await until(pilot, lambda: ("proxy_set_mode", ("tun",)) in remote.calls)
        await pilot.press("a")
        assert app.active_section == "home"
        assert app.query_one('#menu', OptionList).highlighted == 3
    drive(scenario)


def test_prompts_keep_letters_digits_and_arrows_as_text_and_escape_cancels():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("4", "3")
        assert isinstance(app.screen, PromptScreen)
        await pilot.press(*"wasd19", "left", "left", "x")
        assert app.screen.query_one(Input).value == "wasdx19"
        assert app.active_section == "proxy"
        await pilot.press("escape")
        assert not isinstance(app.screen, PromptScreen)
        assert "proxy_set_apps" not in remote.methods()
    drive(scenario)


def test_overview_module_rows_toggle_and_missing_strategy_opens_choices():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("1", "3")
        await until(pilot, lambda: ("tg_start", ()) in remote.calls)
        await until(pilot, lambda: app.data('tg')['running'])
        await pilot.press("3")
        await until(pilot, lambda: ("tg_stop", ()) in remote.calls)
        await pilot.press("1")
        assert app.active_section == "strategies"
        assert "winws_start" not in remote.methods()
    drive(scenario)


def test_overview_hosts_row_and_panic_use_keyboard_confirmation():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("1", "4")
        await until(pilot, lambda: ("hosts_set_enabled", (False,)) in remote.calls)
        await pilot.press("6")
        assert isinstance(app.screen, ConfirmScreen)
        assert not list(app.screen.query(Button))
        await pilot.press("enter")
        assert "panic_all" not in remote.methods()
        await pilot.press("6", "y")
        await until(pilot, lambda: "panic_all" in remote.methods())
        await until(pilot, lambda: "hosts (нужны права)" in app.status_text)
    drive(scenario)


def test_strategy_search_start_stop_and_cancel_search():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("2", "slash", *"dis", "enter")
        pane = app.query_one('#strategies')
        assert pane.search == 'dis'
        assert pane.selected() == 'strategy:discord'
        await pilot.press("enter")
        await until(pilot, lambda: ("winws_start", ("discord",)) in remote.calls)
        await pilot.press("x")
        await until(pilot, lambda: "winws_stop" in remote.methods())
        await pilot.press("slash", "ctrl+a", *"nothing", "escape")
        assert pane.search == 'dis'
    drive(scenario)


def test_lists_use_submenu_to_assign_modules_and_edit_selected_file():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("3")
        await until(pilot, lambda: len(app.query_one('#lists').actions) == 2)
        await pilot.press("2", "2")
        await until(pilot, lambda: ("winws_set_lists", (["discord", "youtube"],)) in remote.calls)
        await pilot.press("2", "3")
        await until(pilot, lambda: ("proxy_set_lists", (["youtube"],)) in remote.calls)
        await pilot.press("e")
        await until(pilot, lambda: isinstance(app.screen, ListEditorScreen) and not app.screen.area.read_only)
        assert app.screen.query_one(TextArea).text == 'youtube.com\n'
        await pilot.press('escape', "2", "4")
        assert app.active_section == "hosts"
    drive(scenario)


def test_proxy_modes_start_add_and_remove_apps_without_buttons():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("4", "2", "2")
        await until(pilot, lambda: ("proxy_set_mode", ("split",)) in remote.calls)
        await pilot.press("1")
        await until(pilot, lambda: "proxy_start" in remote.methods())
        await pilot.press("3", *"x.exe", "enter")
        await until(pilot, lambda: ("proxy_set_apps", (["Discord.exe", "x.exe"],)) in remote.calls)
        await pilot.press("4", "1")
        await until(pilot, lambda: ("proxy_set_apps", (["x.exe"],)) in remote.calls)
    drive(scenario)


def test_hosts_keyboard_picker_and_static_provider_toggle():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("5")
        await until(pilot, lambda: len(app.query_one('#hosts').actions) == 4)
        await pilot.press("3")
        assert isinstance(app.screen, ListPicker)
        await pilot.press("space", "enter")
        await until(pilot, lambda: ("hosts_set_assignments", ({"comss": ["discord"], "malw": ["discord"]},)) in remote.calls)
        await pilot.press("4")
        await until(pilot, lambda: remote.hosts['assignments'].get('flowseal') is True)
        await pilot.press("4")
        await until(pilot, lambda: 'flowseal' not in remote.hosts['assignments'])
    drive(scenario)


def test_hosts_picker_escape_does_not_save():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("5")
        await until(pilot, lambda: len(app.query_one('#hosts').actions) == 4)
        await pilot.press("2", "space", "escape")
        assert "hosts_set_assignments" not in remote.methods()
    drive(scenario)


def test_dns_adapter_provider_confirmation_keep_and_dhcp_reset():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("6")
        await until(pilot, lambda: app.query_one('#dns').adapter == 7)
        await pilot.press("1", "1", "2", "1")
        assert isinstance(app.screen, ConfirmScreen)
        assert "dns_set_trial" not in remote.methods()
        await pilot.press("y")
        await until(pilot, lambda: ("dns_set_trial", (7, "cf", 15)) in remote.calls)
        await until(pilot, lambda: 'keep' in app.query_one('#dns').actions)
        await pilot.press("4")
        await until(pilot, lambda: 'dns_trial_confirm' in remote.methods())
        await pilot.press("3", "n")
        assert 'dns_reset' not in remote.methods()
        await pilot.press("3", "y")
        await until(pilot, lambda: ('dns_reset', (7,)) in remote.calls)
    drive(scenario)


def test_telegram_link_is_shown_and_start_collects_stats():
    remote = FakeRemote()
    remote.tg['link'] = 'tg://proxy?server=127.0.0.1&port=1443&secret=' + SECRET
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("7")
        assert remote.tg['link'] in ' '.join(str(widget.render()) for widget in app.query(Static))
        await pilot.press("1")
        await until(pilot, lambda: 'tg_start' in remote.methods() and 'tg_stats' in remote.methods())
    drive(scenario, remote)


def test_settings_theme_and_language_are_keyboard_choices():
    remote = FakeRemote()
    remote.config['lang'] = 'ru'
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("9")
        await until(pilot, lambda: 'language' in app.query_one('#settings').actions)
        await pilot.press("1", "3")
        await until(pilot, lambda: ('config_set', ('theme', 'dark')) in remote.calls)
        await pilot.press("2", "3")
        await until(pilot, lambda: ('config_set', ('lang', 'en')) in remote.calls)
    drive(scenario, remote)


def test_help_scrolls_in_a_short_terminal_and_blocks_section_shortcuts():
    async def scenario(app, pilot, remote):
        await pilot.resize_terminal(64, 22)
        await pilot.press('question_mark')
        help_view = app.screen.query_one('.help')
        await pilot.press('down', 'down', 'down', 'ctrl+4')
        await until(pilot, lambda: help_view.scroll_y > 0)
        assert app.active_section == 'home'
        await pilot.press('escape')
        assert not isinstance(app.screen, HelpScreen)
    drive(scenario)


def test_connection_reconnects_and_read_only_state_is_not_repainted_every_poll():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.pause(0.3)
        assert app.pushes['winws'] == 1
        remote.offline = True
        await until(pilot, lambda: app.link is False)
        assert 'нет связи' in text(app, '#top')
        remote.offline = False
        await until(pilot, lambda: app.link is True)
        assert 'восстановлена' in app.status_text
    drive(scenario)


def test_offline_actions_are_refused_and_failed_changes_revert():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('1')
        remote.errors['proxy_start'] = 'Нужны права администратора'
        await pilot.press('2')
        await until(pilot, lambda: 'Нужны права' in app.status_text)
        assert not app.data('proxy')['running']
        remote.offline = True
        await until(pilot, lambda: app.link is False)
        await pilot.press('3')
        assert 'tg_start' not in remote.methods()
        assert 'не выполнено' in app.status_text
    drive(scenario)


def test_lazy_data_is_polled_only_for_the_active_section():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        assert 'lists_all' not in remote.methods()
        await pilot.press('3')
        await until(pilot, lambda: 'lists_all' in remote.methods())
        await pilot.press('escape', '1')
        await pilot.pause(0.1)
        count = remote.methods().count('lists_all')
        await pilot.pause(0.3)
        assert remote.methods().count('lists_all') == count
    drive(scenario)


def test_trial_hotkeys_keep_timer_between_sections_and_require_confirmation():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('2', 'down', 'ctrl+t')
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press('y')
        await until(pilot, lambda: ('trial_start', ('strategy', 'discord', 60, None)) in remote.calls)
        await until(pilot, lambda: app.query_one('#trial-status').display)
        await pilot.press('escape', 'ctrl+k')
        await until(pilot, lambda: ('trial_confirm', ('trial-1',)) in remote.calls)
    drive(scenario)


def test_brand_has_full_height_on_start_and_compacts_for_narrow_windows():
    from tui.navigation import LOGO
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        logo = app.query_one('#logo', Static)
        assert logo.content_size.height == len(LOGO.splitlines())
        await pilot.resize_terminal(80, 30)
        await until(pilot, lambda: text(app, '#logo') == LOGO)
        assert app.query_one('#menu').region.bottom <= app.query_one('#keys').region.y
        await pilot.resize_terminal(64, 30)
        await until(pilot, lambda: text(app, '#logo') == 'C H I M E R A')
        assert logo.content_size.height == 1
        await pilot.resize_terminal(100, 35)
        await until(pilot, lambda: text(app, '#logo') == LOGO)
    drive(scenario)


def test_logs_are_text_only_keep_history_position_and_resume_with_end():
    remote = FakeRemote()
    remote.log = ''.join(f'log {i}\n' for i in range(120))
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.resize_terminal(64, 24)
        await pilot.press('8')
        view = app.query_one('#lg-view', RichLog)
        await until(pilot, lambda: len(view.lines) == 120 and view.is_vertical_scroll_end)
        await pilot.press('pageup')
        await until(pilot, lambda: not view.is_vertical_scroll_end)
        await pilot.pause(0.3)
        position = view.scroll_y
        remote.log += 'new first\nnew second\n'
        await until(pilot, lambda: len(view.lines) == 122)
        assert view.scroll_y == position
        await pilot.press('end')
        await until(pilot, lambda: view.is_vertical_scroll_end)
        remote.log += 'latest\n'
        await until(pilot, lambda: len(view.lines) == 123 and view.is_vertical_scroll_end)
        await pilot.press('2')
        await until(pilot, lambda: ('proxy_log', (0,)) in remote.calls)
        assert app.active_section == 'logs'
    drive(scenario, remote)


def test_logs_wrap_and_keep_the_same_line_when_history_is_trimmed(monkeypatch):
    monkeypatch.setattr('tui.panes.LOG_LINES', 40)
    remote = FakeRemote()
    remote.log = ''.join(f'log {i}\n' for i in range(40))
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.resize_terminal(64, 24)
        await pilot.press('8')
        view = app.query_one('#lg-view', RichLog)
        await until(pilot, lambda: len(view.lines) == 40 and view.is_vertical_scroll_end)
        await pilot.press('pageup')
        await until(pilot, lambda: not view.is_vertical_scroll_end)
        await pilot.pause(0.3)
        position = view.scroll_y
        anchor = view.lines[int(position)]
        remote.log += 'new first\nnew second\nnew third\n'
        await until(pilot, lambda: app.query_one('#logs').log_offset == len(remote.log))
        assert view.scroll_y == position - 3
        assert view.lines[int(view.scroll_y)] is anchor
        assert view.max_scroll_x == 0
    drive(scenario, remote)


def test_quit_keeps_chimera_running():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('q')
        assert app._exit
        assert not any(method.endswith('_stop') for method in remote.methods())
    drive(scenario)



def test_runtime_errors_are_visible_in_the_module_menu():
    remote = FakeRemote()
    remote.proxy['error'] = 'test kernel error'
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('4')
        assert 'test kernel error' in text(app, '#proxy-summary')
        assert app.query_one('#proxy-summary').has_class('state-error')
    drive(scenario, remote)


def test_list_refresh_preserves_the_selected_item_in_a_long_menu():
    remote = FakeRemote()
    remote.lists = [{'name': f'list-{i}', 'count': i, 'winws': False, 'proxy': False, 'hosts': False} for i in range(80)]
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.resize_terminal(64, 22)
        await pilot.press('3')
        pane = app.query_one('#lists')
        await until(pilot, lambda: len(pane.actions) == 80)
        await pilot.press(*(['down'] * 30))
        assert pane.selected() == 'list-30'
        remote.lists[0]['count'] += 1
        await until(pilot, lambda: app.data('lists')[0]['count'] == 1)
        assert pane.selected() == 'list-30'
        assert pane.query_one(OptionList).scroll_y > 0
    drive(scenario, remote)


# --- автонастройка --------------------------------------------------------------------------------

def shown(app):
    return str(app.screen.query_one("#autotune-text", Static).render())


def test_autotune_screen_runs_keeps_checks_and_shares_from_the_keyboard(monkeypatch):
    from tui import autotune as tui_autotune
    opened = []
    monkeypatch.setattr(tui_autotune.webbrowser, "open", lambda url: opened.append(url) or True)

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("1", "5")                 # «Обзор» → «Автонастройка»
        assert isinstance(app.screen, tui_autotune.AutotuneScreen)
        await until(pilot, lambda: "Chimera" in shown(app))
        await pilot.press("4")                      # проверить, ничего не меняя
        await until(pilot, lambda: "youtube" in shown(app))
        assert "autotune_start" not in remote.methods()
        await pilot.press("1")                      # настроить всё — быстро
        await until(pilot, lambda: ("autotune_start", (None, "fast")) in remote.calls)
        await until(pilot, lambda: "стратегия alt" in shown(app))
        await pilot.press("7")                      # поделиться
        await until(pilot, lambda: opened == ["https://github.com/emptyenemy/chimera/discussions/new?x"])
        await pilot.press("1")                      # готово — оставить
        await until(pilot, lambda: "autotune_keep" in remote.methods())
        await pilot.press("escape")
        assert not isinstance(app.screen, tui_autotune.AutotuneScreen)
    remote = drive(scenario)
    assert ("fix fast", True) in remote.journal and ("fix keep", True) in remote.journal


def test_autotune_running_shows_progress_on_home_and_only_cancel(monkeypatch):
    async def scenario(app, pilot, remote):
        remote.autotune = {"active": {"id": "s2", "phase": "running", "trigger": "user", "report": None,
                                      "current": {"step": "strategy", "candidate": "alt", "index": 1, "total": 5}},
                           "last": None}
        await online(pilot, app)
        await until(pilot, lambda: "alt" in text(app, "#home-summary"))
        await pilot.press("ctrl+f")
        await until(pilot, lambda: "2 из 5" in shown(app))
        menu = app.screen.query_one(OptionList)
        assert menu.option_count == 1
        await pilot.press("1")
        await until(pilot, lambda: "autotune_cancel" in remote.methods())
    drive(scenario)


def test_fix_one_service_picks_from_the_catalog():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press("ctrl+f", "3")
        await until(pilot, lambda: isinstance(app.screen, MenuScreen))
        await pilot.press("2")
        await until(pilot, lambda: ("autotune_start", (["discord"], "fast")) in remote.calls)
    drive(scenario)



def test_telegram_http2_toggle_changes_saved_flag_in_both_directions():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('ctrl+7', '2')
        await until(pilot, lambda: ('tg_set_advanced', ({'cfproxy_h2_media': False},)) in remote.calls)
        await until(pilot, lambda: app.data('tg').get('cfproxy_h2_media') is False)
        await pilot.press('2')
        await until(pilot, lambda: ('tg_set_advanced', ({'cfproxy_h2_media': True},)) in remote.calls)
        await until(pilot, lambda: app.data('tg').get('cfproxy_h2_media') is True)
    drive(scenario)
