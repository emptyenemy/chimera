"""Задержанные ответы и ошибки записи в клавиатурных меню."""

import asyncio
import threading

from textual.widgets import Input

from tests.test_tui_textual import FakeRemote, drive, online, until
from tui.remote import RemoteError
from tui.screens import PromptScreen


class DelayedRemote(FakeRemote):
    def __init__(self, fail_first=False):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail_first = fail_first
        self.writes = 0

    def m_proxy_set_apps(self, names):
        self.writes += 1
        if self.writes == 1:
            self.entered.set()
            if not self.release.wait(8):
                raise RemoteError('test response timed out')
            if self.fail_first:
                raise RemoteError('write failed')
        return super().m_proxy_set_apps(names)


def test_fast_app_additions_are_serialized_without_losing_names():
    remote = DelayedRemote()

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('4', '3', *'first.exe', 'enter')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('3', *'second.exe', 'enter')
            assert app.data('proxy')['apps'] == ['Discord.exe', 'first.exe', 'second.exe']
            assert remote.writes == 1
            assert remote.proxy['apps'] == ['Discord.exe']
        finally:
            remote.release.set()
        await until(pilot, lambda: not app._writes.pending)
        assert remote.proxy['apps'] == ['Discord.exe', 'first.exe', 'second.exe']
        writes = [args[0] for method, args in remote.calls if method == 'proxy_set_apps']
        assert writes == [['Discord.exe', 'first.exe'], ['Discord.exe', 'first.exe', 'second.exe']]
    drive(scenario, remote)


def test_failed_addition_is_not_leaked_to_the_next_write_and_can_be_retried():
    remote = DelayedRemote(fail_first=True)

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('4', '3', *'first.exe', 'enter')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('3', *'second.exe', 'enter')
        finally:
            remote.release.set()
        await until(pilot, lambda: not app._writes.pending)
        assert remote.proxy['apps'] == ['Discord.exe', 'second.exe']
        pane = app.query_one('#proxy')
        assert pane.failed_apps == ['first.exe']
        await pilot.press('5')
        assert isinstance(app.screen, PromptScreen)
        assert app.screen.query_one(Input).value == 'first.exe'
        await pilot.press('enter')
        await until(pilot, lambda: not app._writes.pending)
        assert remote.proxy['apps'] == ['Discord.exe', 'second.exe', 'first.exe']
        assert not pane.failed_apps
    drive(scenario, remote)


def test_delayed_poll_from_before_a_write_does_not_restore_old_state():
    async def scenario(app, pilot, remote):
        await online(pilot, app)
        old = dict(remote.proxy)
        version = app._writes.versions['proxy']
        await pilot.press('4', '2', '3')
        await until(pilot, lambda: not app._writes.pending)
        assert app.data('proxy')['mode'] == 'tun'
        app._apply({'proxy': old}, True, '', True, {'proxy': version})
        assert app.data('proxy')['mode'] == 'tun'
    drive(scenario)


def test_quit_finishes_both_queued_writes_and_keeps_modules_running():
    remote = DelayedRemote()

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('4', '3', *'first.exe', 'enter')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('3', *'second.exe', 'enter', 'q')
            assert app._quit_requested and not app._exit
        finally:
            remote.release.set()
        for _ in range(200):
            if app._exit:
                break
            await asyncio.sleep(0.01)
        assert app._exit
        assert remote.proxy['apps'] == ['Discord.exe', 'first.exe', 'second.exe']
        assert not any(method.endswith('_stop') for method in remote.methods())
    drive(scenario, remote)


def test_write_failure_cancels_quit_and_keeps_the_failed_value_available():
    remote = DelayedRemote(fail_first=True)

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('4', '3', *'first.exe', 'enter')
        await until(pilot, remote.entered.is_set)
        try:
            await pilot.press('q')
            assert app._quit_requested
        finally:
            remote.release.set()
        await until(pilot, lambda: not app._writes.pending)
        assert not app._exit and not app._quit_requested
        assert app.query_one('#proxy').failed_apps == ['first.exe']
        assert 'write failed' in app.status_text
    drive(scenario, remote)


def test_unexpected_transport_error_releases_the_queue_for_retry():
    remote = FakeRemote()
    original = remote.m_proxy_set_apps

    def broken(names):
        raise ValueError('invalid response')

    remote.m_proxy_set_apps = broken

    async def scenario(app, pilot, remote):
        await online(pilot, app)
        await pilot.press('4', '3', *'first.exe', 'enter')
        await until(pilot, lambda: not app._writes.pending)
        assert 'invalid response' in app.status_text
        assert app.query_one('#proxy').failed_apps == ['first.exe']
        remote.m_proxy_set_apps = original
        await pilot.press('5', 'enter')
        await until(pilot, lambda: 'first.exe' in remote.proxy['apps'])
    drive(scenario, remote)
