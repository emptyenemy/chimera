"""Командная строка внутри TUI: общий с CLI разбор, история без секретов, выполнение через канал."""

import pytest
from textual.widgets import Input, RichLog

from modules.cli.client import CliError
from tests.test_tui_textual import FakeRemote, drive, online, until
from tui import commandline
from tui.console import ConsoleScreen


# --- разбор ----------------------------------------------------------------------------------

def test_prepare_uses_cli_parser_and_accepts_prefixes():
    for value in ('proxy mode split', ':proxy mode split', 'chimera proxy mode split', '  : proxy mode split '):
        invocation = commandline.prepare(value)
        assert invocation.action.command == 'proxy mode'
        assert invocation.arguments['a0'] == 'split'
        assert invocation.changes and not invocation.help


def test_prepare_reads_json_and_lang_flags():
    invocation = commandline.prepare('status --json --lang en')
    assert invocation.as_json and invocation.lang == 'en'
    assert not invocation.changes


@pytest.mark.parametrize('value', ['help', '--help', 'proxy --help', 'proxy mode --help', ''])
def test_help_requests_do_not_touch_modules(value):
    invocation = commandline.prepare(value)
    assert invocation.help and not invocation.changes
    assert invocation.label.startswith('help')


@pytest.mark.parametrize('value, key', [
    ('status && proxy stop', 'tui.console.no_operators'),
    ('status > out.txt', 'tui.console.no_operators'),
    ('tg state --show-secrets', 'tui.console.hidden_secrets'),
    ('proxy mode "split', 'tui.console.quote_error'),
    ('status\x1b[2J', 'tui.console.invalid_input'),
    ('start', 'tui.console.standalone'),
    ('lists save discord', 'tui.console.editor_hint'),
    ('proxy link -', 'tui.console.no_stdin'),
])
def test_prepare_rejects_what_the_console_cannot_run(value, key):
    with pytest.raises(CliError) as caught:
        commandline.prepare(value)
    assert caught.value.key == key


def test_unknown_command_is_a_usage_error():
    with pytest.raises(CliError):
        commandline.prepare('proxy fly')


# --- секреты и история ----------------------------------------------------------------------

@pytest.mark.parametrize('value', [
    'proxy link vless://uuid@host:443', 'tg config --secret abc', 'tg config --sec=abc',
    "tg config '--secret' abc", 'tg advanced fake_tls_domain=x', 'config import tg://proxy?secret=1',
])
def test_sensitive_input_is_detected(value):
    assert commandline.sensitive(value)


@pytest.mark.parametrize('value', ['proxy mode split', 'lists add discord secret.example', 'status'])
def test_ordinary_input_is_not_sensitive(value):
    assert not commandline.sensitive(value)


def test_label_hides_secret_values():
    assert commandline.prepare('tg config --secret abc').label == 'tg config --secret ***'
    assert commandline.prepare('tg config --sec=abc').label == 'tg config --sec=***'


def test_history_skips_secrets_and_repeats_and_keeps_draft():
    history = commandline.History(limit=3)
    for value in ('status', 'status', 'proxy link vless://x', 'proxy mode split', 'lists all', 'tg state'):
        history.add(value)
    assert history.items == ['proxy mode split', 'lists all', 'tg state']
    assert history.move(-1, 'черновик') == 'tg state'
    assert history.move(-1, 'tg state') == 'lists all'
    assert history.move(-5, '') == 'proxy mode split'
    assert history.move(1, '') == 'lists all'
    assert history.move(5, '') == 'черновик'


# --- экран ----------------------------------------------------------------------------------

def _log_text(screen):
    return '\n'.join(strip.text for strip in screen.query_one(RichLog).lines)


async def _open(pilot, app):
    await online(pilot, app)
    await pilot.press('colon')
    await until(pilot, lambda: isinstance(app.screen, ConsoleScreen))
    return app.screen


async def _run(pilot, screen, command):
    await pilot.press(*command, 'enter')
    await until(pilot, lambda: not screen.pending)


def test_colon_opens_console_and_command_changes_module_with_journal_entry():
    async def scenario(app, pilot, remote):
        screen = await _open(pilot, app)
        await _run(pilot, screen, 'proxy mode split')
        assert remote.proxy['mode'] == 'split'
        assert remote.journal == [('proxy mode split', True)]
        assert ': proxy mode split' in _log_text(screen)
        assert app.command_history.items == ['proxy mode split']
        await pilot.press('escape')
        await until(pilot, lambda: not isinstance(app.screen, ConsoleScreen))
    drive(scenario)


def test_failed_command_stays_open_and_is_journaled_as_failure():
    remote = FakeRemote()
    remote.errors['proxy_set_mode'] = 'ядро не найдено'

    async def scenario(app, pilot, remote):
        screen = await _open(pilot, app)
        await _run(pilot, screen, 'proxy mode tun')
        assert 'ядро не найдено' in _log_text(screen)
        assert remote.journal == [('proxy mode tun', False)]
        assert isinstance(app.screen, ConsoleScreen) and not screen.query_one(Input).disabled
    drive(scenario, remote)


def test_usage_error_is_shown_without_calling_modules():
    async def scenario(app, pilot, remote):
        screen = await _open(pilot, app)
        before = len(remote.calls)
        await pilot.press(*'status && proxy stop', 'enter')
        await pilot.pause(0.1)
        assert len(remote.calls) == before or 'proxy_stop' not in remote.methods()[before:]
        assert ': status && proxy stop' in _log_text(screen)
        assert not remote.journal and not app.command_history.items
    drive(scenario)


def test_secret_input_is_masked_and_never_kept():
    async def scenario(app, pilot, remote):
        screen = await _open(pilot, app)
        field = screen.query_one(Input)
        await pilot.press(*'proxy link vless://uuid@host:443')
        assert field.password
        await pilot.press('escape')
        await until(pilot, lambda: not isinstance(app.screen, ConsoleScreen))
        assert app.command_draft == ''
        screen = await _open(pilot, app)
        assert screen.query_one(Input).value == ''
        assert 'vless://' not in _log_text(screen)
        assert not app.command_history.items
    drive(scenario)


def test_read_command_renders_result_and_history_recalls_it():
    async def scenario(app, pilot, remote):
        screen = await _open(pilot, app)
        await _run(pilot, screen, 'lists show discord')
        assert 'discord.com' in _log_text(screen)
        assert not remote.journal
        await pilot.press('up')
        assert screen.query_one(Input).value == 'lists show discord'
    drive(scenario)
