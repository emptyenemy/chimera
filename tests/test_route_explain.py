"""Разбор реальных правил маршрутизации на временных списках, без сети и записи настроек."""

import copy
import json
import socket
from types import SimpleNamespace

import pytest

from modules import domains, i18n, routeexplain
from modules.errors import ChimeraValueError
from ui.api import Api


@pytest.fixture
def rules(tmp_path, monkeypatch):
    lists = tmp_path / 'lists'
    lists.mkdir()
    (lists / 'service.txt').write_text('# service\n.Example.COM\n203.0.113.0/24\n2001:db8::/32\n', encoding='utf-8')
    (lists / 'extra.txt').write_text('api.example.com # exact\nxn--e1afmkfd.xn--p1ai\n', encoding='utf-8')
    hosts = tmp_path / 'hosts'
    hosts.write_text('127.0.0.1 localhost\n203.0.113.2 example.com alias.example\n'
                     '# >>> chimera-hosts >>>\n203.0.113.3 example.com\n# <<< chimera-hosts <<<\n', encoding='utf-8')
    monkeypatch.setattr(domains, 'LISTS_DIR', lists)
    original_lookup = socket.getaddrinfo
    def no_dns(*args, **kwargs):
        if args and args[0] == '127.0.0.1':
            return original_lookup(*args, **kwargs)
        raise AssertionError('route explanation must not use DNS')
    monkeypatch.setattr(socket, 'getaddrinfo', no_dns)
    return {'proxy_config': {'mode': 'pac', 'lists': ['service'], 'apps': ['Discord.exe'],
                              'link': 'vless://private-secret@proxy.example'},
            'proxy_state': {'running': True, 'external': False, 'link': 'private-secret'},
            'winws_config': {'lists': ['service']},
            'winws_state': {'running': True, 'current': 'general', 'external': False},
            'hosts_state': {'enabled': True, 'applied': True, 'assignments': {'comss': ['service', 'extra']}},
            'hosts_path': hosts}


def codes(report):
    return {item['code'] for item in report['warnings']}


def test_suffix_boundary_and_source_lines_explain_every_matching_list(rules):
    report = routeexplain.explain('api.example.com', **rules)
    assert report['proxy']['outbound'] == 'proxy'
    assert report['proxy']['reason'] == 'list'
    by_name = {item['name']: item for item in report['matches']}
    assert by_name['service']['line'] == 2
    assert by_name['service']['entry'] == '.Example.COM'
    assert by_name['service']['dpi'] and by_name['service']['proxy']
    assert by_name['service']['hosts'] == []
    assert by_name['extra']['exact'] and by_name['extra']['hosts'] == ['comss']
    assert report['hosts']['entries'] == []
    assert not report['network_probed']
    assert routeexplain.explain('badexample.com', **rules)['matches'] == []
    assert routeexplain.explain('example.com.evil.test', **rules)['proxy']['outbound'] == 'direct'


def test_hosts_reports_exact_names_aliases_and_overrides_outside_chimera(rules):
    report = routeexplain.explain('example.com', **rules)
    assert report['hosts']['entries'] == [{'ip': '203.0.113.2', 'line': 2, 'source': 'system'},
                                          {'ip': '203.0.113.3', 'line': 4, 'source': 'chimera'}]
    assert 'hosts_conflict' in codes(report)
    alias = routeexplain.explain('alias.example', **rules)
    assert alias['hosts']['entries'] == [{'ip': '203.0.113.2', 'line': 2, 'source': 'system'}]
    assert 'hosts_conflict' not in codes(alias)
    rules['hosts_state']['enabled'] = False
    assert 'hosts_leftover' in codes(routeexplain.explain('example.com', **rules))


def test_stop_and_external_process_are_distinct_from_saved_rules(rules):
    rules['proxy_state']['running'] = False
    stopped = routeexplain.explain('example.com', **rules)
    assert stopped['proxy']['outbound'] == 'direct'
    assert stopped['proxy']['reason'] == 'stopped'
    assert stopped['proxy']['configured_outbound'] == 'proxy'
    rules['proxy_state'].update(running=True, external=True)
    foreign = routeexplain.explain('example.com', **rules)
    assert foreign['proxy']['outbound'] == 'unknown'
    assert foreign['proxy']['reason'] == 'external'


@pytest.mark.parametrize('target', ['10.0.0.1', '172.31.255.254', '192.168.1.1', '127.0.0.1',
                                    '169.254.1.2', '224.0.0.1', '0.0.0.0', '::1', 'fd00::1', 'fe80::1', 'ff02::1'])
def test_tun_local_exception_precedes_application_and_list_rules(rules, target):
    rules['proxy_config'].update(mode='split', apps=['Discord.exe'])
    report = routeexplain.explain(target, app='Discord.exe', **rules)
    assert report['proxy']['outbound'] == 'direct'
    assert report['proxy']['reason'] == 'local'
    rules['proxy_config']['mode'] = 'tun'
    assert routeexplain.explain(target, **rules)['proxy']['reason'] == 'local'


@pytest.mark.parametrize('target', ['100.64.0.1', '192.0.2.1', '203.0.113.1', '2001:db8::1', '8.8.8.8'])
def test_non_public_check_matches_sing_box_instead_of_python_reserved_ranges(rules, target):
    rules['proxy_config']['mode'] = 'tun'
    report = routeexplain.explain(target, **rules)
    assert report['proxy']['outbound'] == 'proxy'
    assert report['proxy']['reason'] == 'all'


def test_split_app_rule_is_exact_and_applies_outside_domain_lists(rules):
    rules['proxy_config']['mode'] = 'split'
    report = routeexplain.explain('unlisted.example', app='Discord.exe', **rules)
    assert report['proxy']['reason'] == 'app'
    assert report['proxy']['outbound'] == 'proxy'
    wrong_case = routeexplain.explain('unlisted.example', app='discord.exe', **rules)
    assert wrong_case['proxy']['outbound'] == 'direct'
    assert 'app_case' in codes(wrong_case)
    unknown = routeexplain.explain('unlisted.example', **rules)
    assert 'app_unknown' in codes(unknown)
    assert 'dns_unknown' in codes(unknown)
    rules['proxy_config']['mode'] = 'pac'
    assert routeexplain.explain('unlisted.example', app='Discord.exe', **rules)['proxy']['outbound'] == 'direct'


def test_pac_ipv6_subnets_have_different_coverage_from_tun_and_exact_addresses(rules):
    report = routeexplain.explain('2001:db8::2', **rules)
    assert report['matches'][0]['kind'] == 'network'
    assert not report['matches'][0]['pac_supported']
    assert report['proxy']['outbound'] == 'direct'
    assert report['proxy']['reason'] == 'pac_ipv6'
    assert 'pac_ipv6' in codes(report)
    rules['proxy_config']['mode'] = 'split'
    assert routeexplain.explain('2001:db8::2', **rules)['proxy']['outbound'] == 'proxy'
    rules['proxy_config']['mode'] = 'pac'
    path = domains.LISTS_DIR / 'service.txt'
    with path.open('a', encoding='utf-8') as stream:
        stream.write('2001:db8::2\n')
    exact = routeexplain.explain('2001:db8::2', **rules)
    assert exact['proxy']['outbound'] == 'proxy'
    assert 'pac_ipv6' not in codes(exact)


def test_missing_selected_lists_do_not_hide_the_rest_of_the_report(rules):
    rules['proxy_config']['lists'].append('missing')
    report = routeexplain.explain('example.com', **rules)
    assert report['proxy']['outbound'] == 'proxy'
    assert {'code': 'list_unreadable', 'detail': 'missing'} in report['warnings']


def test_report_never_claims_user_lists_cover_the_entire_dpi_strategy(rules):
    report = routeexplain.explain('unlisted.example', **rules)
    assert report['dpi']['running'] and report['dpi']['lists'] == []
    assert 'dpi_scope' in codes(report)
    rules['winws_state']['external'] = True
    assert 'external_dpi' in codes(routeexplain.explain('unlisted.example', **rules))


def test_explanation_is_read_only_and_does_not_export_proxy_secrets(rules):
    original = copy.deepcopy(rules)
    before = {path: path.read_bytes() for path in [rules['hosts_path'], *domains.LISTS_DIR.iterdir()]}
    report = routeexplain.explain('https://EXAMPLE.com:443/path?token=private-secret#fragment', **rules)
    assert report['target'] == 'example.com'
    assert 'private-secret' not in json.dumps(report)
    assert rules == original
    assert before == {path: path.read_bytes() for path in before}


@pytest.mark.parametrize(('value', 'expected'), [('EXAMPLE.com.', 'example.com'),
    ('https://пример.рф/path', 'xn--e1afmkfd.xn--p1ai'), ('[2001:db8::1]', '2001:db8::1'),
    ('https://[2001:db8::1]:443/path', '2001:db8::1')])
def test_target_normalization(value, expected):
    assert routeexplain.normalize_target(value)[0] == expected


@pytest.mark.parametrize('value', ['', None, [], 'bad/name', '*.example.com', 'a..b', 'example.com:443',
    'https://user:secret@example.com/', 'vless://secret@example.com', 'https://example.com:65536',
    'https://example.com:bad', '999.999.999.999', '1.2.3', 'example.com\n', '\x1b[31mexample.com', 'example.com\u202e', 'fe80::1%eth0'])
def test_invalid_input_is_rejected_without_echoing_sensitive_values(value):
    with pytest.raises(ChimeraValueError) as error:
        routeexplain.normalize_target(value)
    assert error.value.code == 'err.route.target' and error.value.params == {}


def test_render_is_localized_and_includes_actionable_sources(rules):
    report = routeexplain.explain('example.com', **rules)
    with i18n.using('ru'):
        ru = '\n'.join(routeexplain.render(report))
    with i18n.using('en'):
        en = '\n'.join(routeexplain.render(report))
    assert 'Причина:' in ru and 'service:2' in ru and 'блок Chimera' in ru
    assert 'Reason:' in en and 'Chimera block' in en
    assert '2001:db8' not in en


def test_api_exposes_read_only_explanation_with_the_owners_state(rules, monkeypatch):
    api = Api.__new__(Api)
    api._service_owned = True
    api.proxy = SimpleNamespace(config=rules['proxy_config'], state=lambda: rules['proxy_state'])
    api.winws = SimpleNamespace(config=rules['winws_config'], state=lambda: rules['winws_state'])
    api.hosts = SimpleNamespace(state=lambda: rules['hosts_state'], hosts_path=rules['hosts_path'])
    assert Api.is_read('route_explain')
    reply = json.loads(api.dispatch('route_explain', '["example.com"]'))
    assert reply['ok'] and reply['data']['proxy']['reason'] == 'list'
    invalid = api.route_explain('https://user:secret@example.com')
    assert not invalid['ok'] and invalid['code'] == 'err.route.target'
    monkeypatch.setattr(api, '_backup_owner', lambda method, *args: {'ok': True, 'data': {'owner': 'service'}})
    assert api.route_explain('example.com')['data'] == {'owner': 'service'}
