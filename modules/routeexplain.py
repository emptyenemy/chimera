"""Локальное объяснение правил Chimera для адреса, без DNS и сетевых проверок."""

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

from modules import domains
from modules.errors import ChimeraValueError
from modules.i18n import LazyMap, t

REASONS = LazyMap(('stopped', 'external', 'local', 'all', 'app', 'list', 'default', 'pac_ipv6'),
                  'msg.route.reason')
WARNINGS = LazyMap(('pac', 'pac_ipv6', 'dns_unknown', 'app_unknown', 'app_case', 'dpi_scope',
                   'external_dpi', 'hosts_conflict', 'hosts_leftover', 'hosts_unreadable', 'list_unreadable'),
                  'msg.route.warning')
OUTBOUNDS = LazyMap(('direct', 'proxy', 'unknown'), 'msg.route.outbound')
_PRIVATE = tuple(ipaddress.ip_network(value) for value in
                 ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))
_LABEL = re.compile(r'(?!-)[a-z0-9_-]{1,63}(?<!-)')


def normalize_target(value):
    if not isinstance(value, str) or len(value) > 2048 or any(unicodedata.category(c).startswith('C') for c in value):
        raise ChimeraValueError('err.route.target')
    value = value.strip()
    if not value:
        raise ChimeraValueError('err.route.target')
    try:
        if '://' in value:
            url = urlsplit(value)
            if url.scheme.lower() not in ('http', 'https') or url.username is not None or url.password is not None:
                raise ValueError
            if url.port is not None and not 1 <= url.port <= 65535:
                raise ValueError
            value = url.hostname or ''
        elif value.startswith('[') and value.endswith(']'):
            value = value[1:-1]
        try:
            addr = ipaddress.ip_address(value)
            if '%' in value:
                raise ValueError
            return str(addr), addr
        except ValueError:
            if ':' in value or '%' in value:
                raise ValueError from None
        if re.fullmatch(r'[0-9.]+', value):
            raise ValueError
        value = value.rstrip('.').encode('idna').decode('ascii').lower()
        if len(value) > 253 or not all(_LABEL.fullmatch(label) for label in value.split('.')):
            raise ValueError
        return value, None
    except (ValueError, UnicodeError):
        raise ChimeraValueError('err.route.target') from None


def normalize_app(value):
    if value is None or value == '':
        return None
    if (not isinstance(value, str) or len(value) > 260 or '/' in value or '\\' in value
            or any(unicodedata.category(c).startswith('C') for c in value)):
        raise ChimeraValueError('err.route.app')
    return value.strip() or None


def non_public(addr):
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_unspecified
            or any(addr.version == net.version and addr in net for net in _PRIVATE))


def _hosts_entries(path, target):
    entries, own = [], False
    if path is None or not path.exists():
        return entries
    for line, raw in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
        if raw.strip() == '# >>> chimera-hosts >>>':
            own = True
        elif raw.strip() == '# <<< chimera-hosts <<<':
            own = False
        words = raw.split('#', 1)[0].split()
        if len(words) < 2 or target not in [alias.lower().rstrip('.') for alias in words[1:]]:
            continue
        try:
            address = str(ipaddress.ip_address(words[0]))
        except ValueError:
            continue
        entries.append({'ip': address, 'line': line, 'source': 'chimera' if own else 'system'})
    return entries


def explain(target, *, proxy_config, proxy_state, winws_config, winws_state, hosts_state, hosts_path=None, app=None):
    target, addr = normalize_target(target)
    app = normalize_app(app)
    proxy_lists = set(proxy_config.get('lists') or [])
    dpi_lists = set(winws_config.get('lists') or [])
    assignments = hosts_state.get('assignments') or {}
    mode = proxy_config.get('mode', 'pac')
    mode = mode if mode in ('split', 'tun') else 'pac'
    matches, warnings = [], []
    names = set(domains.available_lists()) | proxy_lists | dpi_lists
    names.update(name for value in assignments.values() if isinstance(value, list) for name in value)
    for name in sorted(names):
        try:
            text = domains.read_raw(name)
        except (OSError, ValueError, ChimeraValueError):
            warnings.append({'code': 'list_unreadable', 'detail': name})
            continue
        for number, raw in enumerate(text.splitlines(), 1):
            entry = raw.split('#', 1)[0].strip()
            dom, nets = domains.split_entries([entry])
            net = domains.as_network(nets[0]) if nets else None
            if addr is not None:
                hit = net is not None and net.version == addr.version and addr in net
            else:
                hit = bool(dom and (target == dom[0] or target.endswith('.' + dom[0])))
            if not hit:
                continue
            exact = addr is None and target == dom[0]
            providers = [pid for pid, selected in assignments.items()
                         if exact and isinstance(selected, list) and name in selected]
            matches.append({'name': name, 'line': number, 'entry': entry,
                            'kind': 'network' if net else 'domain', 'exact': exact,
                            'dpi': name in dpi_lists, 'proxy': name in proxy_lists, 'hosts': providers,
                            'pac_supported': net is None or net.version == 4 or net.prefixlen == 128})

    proxy_matches = [item for item in matches if item['proxy']]
    usable = [item for item in proxy_matches if mode != 'pac' or item['pac_supported']]
    apps = list(proxy_config.get('apps') or [])
    if mode != 'pac' and addr is not None and non_public(addr):
        configured, rule = 'direct', 'local'
    elif mode == 'tun':
        configured, rule = 'proxy', 'all'
    elif mode == 'split' and app in apps:
        configured, rule = 'proxy', 'app'
    elif usable:
        configured, rule = 'proxy', 'list'
    elif proxy_matches and mode == 'pac':
        configured, rule = 'direct', 'pac_ipv6'
    else:
        configured, rule = 'direct', 'default'
    if mode == 'pac':
        warnings.append({'code': 'pac'})
        if proxy_matches and not usable:
            warnings.append({'code': 'pac_ipv6'})
    elif addr is None:
        warnings.append({'code': 'dns_unknown'})
    if mode == 'split' and apps:
        if app is None:
            warnings.append({'code': 'app_unknown'})
        elif app not in apps and app.casefold() in [name.casefold() for name in apps]:
            warnings.append({'code': 'app_case'})
    running = bool(proxy_state.get('running'))
    external = bool(proxy_state.get('external'))
    outbound, reason = (('direct', 'stopped') if not running else
                        ('unknown', 'external') if external else (configured, rule))
    warnings.append({'code': 'external_dpi' if winws_state.get('external') else 'dpi_scope'})
    host_entries = []
    if addr is None:
        try:
            host_entries = _hosts_entries(hosts_path, target)
        except OSError:
            warnings.append({'code': 'hosts_unreadable'})
    if host_entries:
        ours = {item['ip'] for item in host_entries if item['source'] == 'chimera'}
        others = {item['ip'] for item in host_entries if item['source'] == 'system'}
        if ours and others and ours != others:
            warnings.append({'code': 'hosts_conflict'})
        if ours and not hosts_state.get('enabled', True):
            warnings.append({'code': 'hosts_leftover'})
    return {'target': target, 'kind': 'ip' if addr is not None else 'domain', 'app': app,
            'network_probed': False, 'matches': matches,
            'proxy': {'running': running, 'external': external, 'mode': mode, 'outbound': outbound,
                      'reason': reason, 'configured_outbound': configured, 'configured_reason': rule},
            'dpi': {'running': bool(winws_state.get('running')), 'external': bool(winws_state.get('external')),
                    'strategy': winws_state.get('current'),
                    'lists': sorted({item['name'] for item in matches if item['dpi']})},
            'hosts': {'enabled': bool(hosts_state.get('enabled', True)),
                      'applied': bool(hosts_state.get('applied')), 'entries': host_entries},
            'warnings': warnings}


def render(report):
    proxy, dpi = report['proxy'], report['dpi']
    lines = [t('msg.route.target', target=report['target']),
             t('msg.route.proxy', outbound=OUTBOUNDS[proxy['outbound']], mode=proxy['mode']),
             t('msg.route.reason_line', reason=REASONS[proxy['reason']])]
    if proxy['reason'] in ('stopped', 'external'):
        lines.append(t('msg.route.configured', outbound=OUTBOUNDS[proxy['configured_outbound']],
                       reason=REASONS[proxy['configured_reason']]))
    if report['app']:
        lines.append(t('msg.route.app', app=report['app']))
    lines.append(t('msg.route.dpi', state=t('msg.route.running' if dpi['running'] else 'msg.route.stopped'),
                   strategy=dpi['strategy'] or '—', lists=', '.join(dpi['lists']) or '—'))
    lines.extend(['', t('msg.route.matches')])
    for item in report['matches']:
        tools = (['DPI'] if item['dpi'] else []) + (['Proxy'] if item['proxy'] else [])
        tools.extend('Hosts: ' + provider for provider in item['hosts'])
        lines.append(f"  {item['name']}:{item['line']}  {item['entry']} → {', '.join(tools) or '—'}")
    if not report['matches']:
        lines.append('  ' + t('msg.route.no_matches'))
    lines.extend(['', t('msg.route.hosts')])
    for entry in report['hosts']['entries']:
        source = t('msg.route.hosts_own' if entry['source'] == 'chimera' else 'msg.route.hosts_other')
        lines.append(f"  {entry['ip']}  {source} · {entry['line']}")
    if not report['hosts']['entries']:
        lines.append('  ' + t('msg.route.no_hosts'))
    lines.extend(['', t('msg.route.notes')])
    for warning in report['warnings']:
        lines.append('  ' + WARNINGS[warning['code']] + (': ' + warning['detail'] if warning.get('detail') else ''))
    lines.append('  ' + t('msg.route.local_only'))
    return lines
