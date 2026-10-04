"""Пассивный разбор маршрута клавиатурой и безопасность запоздалого ответа."""

import threading

from textual.containers import VerticalScroll
from textual.widgets import Button, TextArea

from modules import routeexplain
from tests import test_route_explain
from tests.test_tui_textual import FakeRemote, drive, online, until
from tui.route_report import RouteReportScreen
from tui.screens import PromptScreen


rules = test_route_explain.rules


class RouteRemote(FakeRemote):
    def __init__(self, rules):
        super().__init__()
        self.rules = rules

    def m_route_explain(self, target):
        return routeexplain.explain(target, **self.rules)


def test_ctrl_e_opens_a_plain_keyboard_report_and_escape_returns_to_the_same_section(rules):
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('4', 'ctrl+e')
        assert isinstance(app.screen, PromptScreen)
        await pilot.press(*'example.com', 'enter')
        await until(pilot, lambda: isinstance(app.screen, RouteReportScreen) and not app.screen.busy)
        screen = app.screen
        content = str(screen.query_one('#route-text').render())
        assert 'Причина:' in content and 'service:2' in content
        assert '203.0.113.3' in content
        assert not list(screen.query(Button))
        assert screen.query_one(VerticalScroll).styles.scrollbar_size_vertical == 0
        assert not remote.journal
        await pilot.press('escape')
        assert app.active_section == 'proxy'
    drive(scenario, RouteRemote(rules))


def test_overview_explain_row_and_cancel_do_not_change_modules(rules):
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('1', '7')
        assert isinstance(app.screen, PromptScreen)
        await pilot.press(*'example.com', 'escape')
        assert app.active_section == 'overview'
        assert 'route_explain' not in remote.methods()
        assert not remote.journal
    drive(scenario, RouteRemote(rules))


def test_report_failure_keeps_retry_available(rules):
    remote = RouteRemote(rules)
    remote.errors['route_explain'] = 'owner unavailable'

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('ctrl+e', *'example.com', 'enter')
        await until(pilot, lambda: isinstance(app.screen, RouteReportScreen) and not app.screen.busy)
        screen = app.screen
        assert 'owner unavailable' in str(screen.query_one('#route-text').render())
        remote.errors.clear()
        await pilot.press('f5')
        await until(pilot, lambda: not screen.busy)
        assert 'service:2' in str(screen.query_one('#route-text').render())
        assert not remote.journal
    drive(scenario, remote)


def test_late_report_after_escape_does_not_open_a_screen_or_crash(rules):
    remote = RouteRemote(rules)
    entered, release = threading.Event(), threading.Event()
    original = remote.m_route_explain

    def delayed(target):
        entered.set()
        if not release.wait(8):
            raise RuntimeError('test response timed out')
        return original(target)

    remote.m_route_explain = delayed

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('ctrl+e', *'example.com', 'enter')
        await until(pilot, entered.is_set)
        try:
            await pilot.press('escape', '4')
            assert app.active_section == 'proxy'
        finally:
            release.set()
        await pilot.pause(0.1)
        assert app.active_section == 'proxy' and not isinstance(app.screen, RouteReportScreen)
    drive(scenario, remote)


def test_ctrl_e_in_the_editor_keeps_its_native_cursor_action(rules):
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        app.edit_list('discord')
        await until(pilot, lambda: app.screen.query_one(TextArea).read_only is False)
        await pilot.press('home', 'ctrl+e')
        assert app.screen.area.selection.end == (0, len('# Discord'))
        assert 'route_explain' not in remote.methods()
    drive(scenario, RouteRemote(rules))
