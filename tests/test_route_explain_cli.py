"""Публичная команда explain проходит через настоящий канал с фиктивным Api."""

import pytest

from modules import routeexplain
from modules.cli import commands
from tests import test_cli, test_route_explain

run, run_json = test_cli.run, test_cli.run_json
running, stopped = test_cli.running, test_cli.stopped
rules = test_route_explain.rules


@pytest.fixture
def report(rules):
    return routeexplain.explain('example.com', **rules)


def test_explain_json_includes_sources_uses_read_level_and_does_not_write_a_journal(running, capsys, report):
    api, _server = running
    api.extra['route_explain'] = report
    code, data, error = run_json(capsys, 'explain', 'https://EXAMPLE.com/path', '--app', 'Discord.exe')
    assert code == 0 and not error
    assert data['command'] == 'explain' and data['level'] == 'read'
    assert data['data']['matches'][0]['name'] == 'service'
    assert api.called('route_explain') == [['example.com', 'Discord.exe']]
    assert not commands.CHANGES_LOG.exists()


def test_explain_has_localized_human_output(running, capsys, report):
    api, _server = running
    api.extra['route_explain'] = report
    code, output, error = run(capsys, 'explain', 'example.com', '--lang', 'en')
    assert code == 0 and not error
    assert 'Address: example.com' in output and 'Reason:' in output
    assert 'service:2' in output and 'Chimera block' in output


def test_invalid_or_sensitive_target_is_rejected_before_any_remote_call(running, capsys):
    api, _server = running
    code, data, _error = run_json(capsys, 'explain', 'https://user:private-secret@example.com/')
    assert code != 0 and not data['ok']
    assert data['error']['key'] == 'err.route.target'
    assert not api.called('route_explain')
    assert 'private-secret' not in str(data)


def test_explain_refuses_without_an_owner_and_never_starts_chimera(stopped, capsys):
    code, data, _error = run_json(capsys, 'explain', 'example.com')
    assert code == 3 and not data['ok']
    assert data['error']['code'] == 'not_running'


def test_explain_help_describes_app_matching_and_read_only_operation(capsys):
    code, output, error = run(capsys, 'explain', '--help', '--lang', 'en')
    assert code == 0 and not error
    assert '--app' in output and 'DNS' in output
