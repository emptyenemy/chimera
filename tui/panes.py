"""Клавиатурные разделы: текстовые строки состояния и меню команд."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import OptionList, RichLog, Static
from textual.widgets.option_list import Option

from modules.i18n import t as _tr
from tui.screens import ListPicker, MenuScreen, PromptScreen


def tag(ok, on=None, off=None):
    return ('[+] ' + (on or _tr('tui.panes.running'))) if ok else ('[-] ' + (off or _tr('tui.panes.stopped')))


class Pane(Vertical):
    KEYS = ()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.actions = {}

    def compose(self) -> ComposeResult:
        yield Static('', id=f'{self.id}-summary', classes='pane-summary', markup=False)
        yield OptionList(id=f'{self.id}-actions')

    def on_mount(self):
        self.render_state()

    def state_changed(self, keys):
        if self.is_mounted and (not self.KEYS or set(keys) & set(self.KEYS)):
            self.render_state()

    def render_state(self):
        pass

    def sources(self):
        return []

    def focus_primary(self):
        self.query_one(OptionList).focus()

    def trial_target(self):
        return None

    def summary(self, value):
        errors = []
        for key in self.KEYS:
            state = self.app.data(key)
            error = self.app.error(key) or (state.get('error') if isinstance(state, dict) else None)
            if error:
                errors.append(f'{key}: {error}')
        widget = self.query_one(f'#{self.id}-summary', Static)
        widget.update(value + ('\n' + '\n'.join(errors) if errors else ''))
        widget.set_class(bool(errors), 'state-error')

    def menu(self, entries):
        menu = self.query_one(OptionList)
        previous, index = None, menu.highlighted or 0
        if menu.highlighted is not None and menu.option_count:
            previous = menu.get_option_at_index(menu.highlighted).id
        self.actions = {key: action for key, _, action in entries}
        menu.clear_options()
        menu.add_options(Option(Text(f'{i:>2}. {label}'), id=key) for i, (key, label, _) in enumerate(entries, 1))
        ids = list(self.actions)
        if ids:
            menu.highlighted = ids.index(previous) if previous in ids else min(index, len(ids) - 1)

    def choose_number(self, number):
        menu = self.query_one(OptionList)
        if number <= menu.option_count:
            menu.highlighted = number - 1
            menu.action_select()

    def selected(self):
        menu = self.query_one(OptionList)
        return menu.get_option_at_index(menu.highlighted).id if menu.highlighted is not None else None

    def on_option_list_option_selected(self, event):
        event.stop()
        action = self.actions.get(event.option.id)
        if action:
            action()

    def choose(self, title, choices, callback):
        self.app.push_screen(MenuScreen(title, choices), lambda value: callback(value) if value is not None else None)

    def prompt(self, title, callback, value=''):
        self.app.push_screen(PromptScreen(title, value), lambda value: callback(value) if value is not None else None)


MODULES = (('winws', _tr('tui.panes.dpi_bypass_winws')), ('proxy', _tr('tui.panes.proxy_sing_box')),
           ('tg', _tr('tui.panes.telegram_proxy')), ('hosts_state', 'Hosts'))


class OverviewPane(Pane):
    KEYS = ('app', 'winws', 'proxy', 'tg', 'hosts_state')

    def render_state(self):
        info = self.app.data('app') or {}
        self.summary(_tr('tui.classic.overview', version=info.get('version', '?')))
        entries = []
        for key, title in MODULES:
            state = self.app.data(key) or {}
            active = state.get('enabled') if key == 'hosts_state' else state.get('running')
            detail = state.get('current') or state.get('mode') or ''
            status = _tr('tui.classic.enabled') if active else _tr('tui.classic.disabled')
            label = f"{title}: {status if key == 'hosts_state' else tag(active)}" + (f' · {detail}' if detail else '')
            entries.append((key, label, lambda key=key: self.toggle(key)))
        entries.append(('panic', _tr('tui.panes.turn_everything_off'), self.panic))
        entries.append(('explain', _tr('tui.route.title'), self.app.action_explain))
        self.menu(entries)

    def toggle(self, key):
        state = self.app.data(key) or {}
        flag = 'enabled' if key == 'hosts_state' else 'running'
        want = not state.get(flag)
        if key == 'hosts_state':
            method, args = 'hosts_set_enabled', lambda target: (target['enabled'],)
        else:
            prefix = 'tg' if key == 'tg' else key
            method, args = prefix + ('_start' if want else '_stop'), lambda target: ()
            if key == 'winws' and want:
                sid = state.get('last_strategy')
                if not sid:
                    self.app.open_section('strategies')
                    return
                def args(target):
                    return (sid,)
        self.app.write_state(_tr('tui.classic.module_change', module=key), key, method,
                             lambda state: {**state, flag: want}, args, journal=method)

    def panic(self):
        def done(result):
            failed = [f"{item['step']} ({item.get('error')})" for item in (result or {}).get('steps', []) if not item.get('ok')]
            if failed:
                self.app.status(_tr('tui.panes.turn_everything_off_failed') + '; '.join(failed), error=True)
        self.app.confirm(_tr('tui.panes.turn_off_bypass_proxy_telegram_proxy_service_and'),
                         lambda: self.app.act(_tr('tui.panes.turn_everything_off'), 'panic_all', journal='panic', after=done))


class StrategiesPane(Pane):
    KEYS = ('winws',)
    BINDINGS = [Binding('slash', 'search', '', show=False), Binding('x', 'stop', '', show=False)]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search = ''

    def render_state(self):
        state = self.app.data('winws') or {}
        self.summary(tag(state.get('running')) + ' · ' + (state.get('current') or state.get('last_strategy') or '—'))
        entries = [('search', _tr('tui.classic.search', query=self.search or '—'), self.action_search),
                   ('stop', _tr('tui.panes.stop_bypass'), self.action_stop)]
        for item in state.get('strategies') or []:
            sid = item.get('id', '')
            description = item.get('desc') or item.get('name') or ''
            if self.search.lower() not in (sid + ' ' + description).lower():
                continue
            mark = '[*]' if state.get('running') and state.get('current') == sid else '[ ]'
            entries.append(('strategy:' + sid, f'{mark} {sid} · {description}', lambda sid=sid: self.start(sid)))
        self.menu(entries)

    def focus_primary(self):
        super().focus_primary()
        if self.query_one(OptionList).option_count > 2:
            self.query_one(OptionList).highlighted = 2

    def action_search(self):
        def changed(value):
            self.search = value.strip()
            self.render_state()
            self.focus_primary()
        self.prompt(_tr('tui.panes.search_strategies'), changed, self.search)

    def start(self, sid):
        self.app.write_state(_tr('tui.panes.starting_strategy', p0=sid), 'winws', 'winws_start',
                             lambda state: {**state, 'running': True, 'current': sid, 'last_strategy': sid},
                             lambda target: (sid,), journal=f'winws start {sid}')

    def action_stop(self):
        self.app.write_state(_tr('tui.panes.stopping_bypass'), 'winws', 'winws_stop',
                             lambda state: {**state, 'running': False, 'current': None}, lambda target: (), journal='winws stop')

    def trial_target(self):
        sid = self.selected() or ''
        return ('strategy', sid[9:]) if sid.startswith('strategy:') else None


class ListsPane(Pane):
    KEYS = ('lists',)
    BINDINGS = [Binding('e', 'edit', '', show=False)]

    def sources(self):
        return [('lists', 'lists_all', (), 3)]

    def render_state(self):
        self.summary(self.app.error('lists') or _tr('tui.classic.lists'))
        entries = []
        for item in self.app.data('lists') or []:
            name = item['name']
            active = [title for key, title in (('winws', 'DPI'), ('proxy', _tr('tui.textual_app.proxy')), ('hosts', 'Hosts')) if item.get(key)]
            draft = ' *' if name in self.app.list_drafts else ''
            label = f"{name}{draft} · {item.get('count', 0)} · {', '.join(active) or '—'}"
            entries.append((name, label, lambda name=name: self.open_list(name)))
        self.menu(entries)

    def open_list(self, name):
        item = next((item for item in self.app.data('lists') or [] if item['name'] == name), {})
        choices = [('edit', _tr('tui.classic.edit_file')),
                   ('winws', 'DPI: ' + tag(item.get('winws'))),
                   ('proxy', _tr('tui.textual_app.proxy') + ': ' + tag(item.get('proxy'))),
                   ('hosts', _tr('tui.classic.hosts_assignments'))]
        def chosen(key):
            if key == 'edit':
                self.app.edit_list(name)
            elif key == 'hosts':
                self.app.open_section('hosts')
            else:
                want = not item.get(key)
                self.app.write_state(name, 'lists', 'winws_set_lists' if key == 'winws' else 'proxy_set_lists',
                    lambda items: [{**row, key: want} if row['name'] == name else row for row in items],
                    lambda items: ([row['name'] for row in items if row.get(key)],), journal=f'{key} list {name} {want}')
        self.choose(name, choices, chosen)

    def action_edit(self):
        if self.selected():
            self.app.edit_list(self.selected())


MODES = (('pac', _tr('tui.panes.pac_no_administrator_rights')), ('split', _tr('tui.panes.selective_tun_applications')),
         ('tun', _tr('tui.panes.tun_all_traffic')))


class ProxyPane(Pane):
    KEYS = ('proxy',)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.failed_apps = []

    def render_state(self):
        state = self.app.data('proxy') or {}
        core = state.get('core') or {}
        self.summary(tag(state.get('running')) + ' · sing-box ' + (core.get('version') or '—'))
        entries = [('toggle', _tr('tui.panes.stop') if state.get('running') else _tr('tui.panes.start'), self.toggle),
                   ('mode', _tr('tui.classic.proxy_mode', mode=state.get('mode', 'pac')), self.mode),
                   ('add', _tr('tui.classic.add_app'), lambda: self.add_app()),
                   ('apps', _tr('tui.classic.apps', count=len(state.get('apps') or [])), self.apps)]
        entries.extend(('retry:' + name, _tr('tui.classic.retry_app', name=name), lambda name=name: self.add_app(name)) for name in self.failed_apps)
        self.menu(entries)

    def toggle(self):
        want = not (self.app.data('proxy') or {}).get('running')
        method = 'proxy_start' if want else 'proxy_stop'
        self.app.write_state(_tr('tui.classic.module_change', module='proxy'), 'proxy', method,
                             lambda state: {**state, 'running': want}, lambda target: (), journal=method)

    def mode(self):
        def changed(mode):
            self.app.write_state(_tr('tui.panes.proxy_mode', p0=mode), 'proxy', 'proxy_set_mode',
                                 lambda state: {**state, 'mode': mode}, lambda target: (target['mode'],), journal=f'proxy mode {mode}')
        self.choose(_tr('tui.classic.choose_proxy_mode'), MODES, changed)

    def add_app(self, retry=''):
        def added(value):
            name = value.strip()
            if not name:
                return
            def patch(state):
                apps = list(state.get('apps') or [])
                if name.lower() not in [item.lower() for item in apps]:
                    apps.append(name)
                return {**state, 'apps': apps}
            def failed():
                if name not in self.failed_apps:
                    self.failed_apps.append(name)
                self.render_state()
            def saved(_result):
                self.failed_apps = [item for item in self.failed_apps if item != name]
                self.render_state()
            self.app.write_state(_tr('tui.panes.application', p0=name), 'proxy', 'proxy_set_apps', patch,
                                 lambda state: (state['apps'],), journal=f'proxy apps +{name}', after=saved, failed=failed)
        self.prompt(_tr('tui.classic.add_app'), added, retry)

    def apps(self):
        names = list((self.app.data('proxy') or {}).get('apps') or [])
        self.choose(_tr('tui.classic.remove_app'), [(name, name) for name in names],
            lambda name: self.app.write_state(_tr('tui.panes.remove', p0=name), 'proxy', 'proxy_set_apps',
                lambda state: {**state, 'apps': [item for item in state.get('apps') or [] if item != name]},
                lambda state: (state['apps'],), journal=f'proxy apps -{name}'))

    def trial_target(self):
        mode = (self.app.data('proxy') or {}).get('mode')
        return 'tun', 'split' if mode == 'split' else 'tun'


class HostsPane(Pane):
    KEYS = ('hosts', 'hosts_state')

    def sources(self):
        return [('hosts', 'hosts_overview', (), 3)]

    def render_state(self):
        state = self.app.data('hosts_state') or {}
        applied = _tr('tui.classic.applied') if state.get('applied') else _tr('tui.classic.not_applied')
        self.summary(_tr('tui.classic.hosts_state', count=state.get('count', 0)) + ' · ' + applied)
        entries = [('toggle', 'Hosts: ' + tag(state.get('enabled')), self.toggle)]
        assigned = state.get('assignments') or {}
        for provider in (self.app.data('hosts') or {}).get('providers') or []:
            pid = provider['id']
            value = assigned.get(pid)
            status = tag(bool(value)) if provider.get('type') == 'static' else ', '.join(value or []) or '—'
            entries.append((pid, (provider.get('name') or pid) + ': ' + status, lambda provider=provider: self.provider(provider)))
        self.menu(entries)

    def toggle(self):
        OverviewPane.toggle(self, 'hosts_state')

    def provider(self, provider):
        pid = provider['id']
        assigned = (self.app.data('hosts_state') or {}).get('assignments') or {}
        def save(value):
            def patch(state):
                mapping = {**(state.get('assignments') or {}), pid: value}
                return {**state, 'assignments': {key: item for key, item in mapping.items() if item}}
            self.app.write_state(_tr('tui.panes.lists_for_provider', p0=pid), 'hosts_state', 'hosts_set_assignments',
                                 patch, lambda state: (state['assignments'],), journal=f'hosts assign {pid}')
        if provider.get('type') == 'static':
            save(not assigned.get(pid))
        else:
            names = [item['name'] for item in (self.app.data('hosts') or {}).get('lists') or []]
            self.app.push_screen(ListPicker(provider.get('name') or pid, names, assigned.get(pid) or []),
                                 lambda result: save(result) if result is not None else None)

    def trial_target(self):
        return 'hosts', 'off' if (self.app.data('hosts_state') or {}).get('applied') else 'on'


TRIAL_SECONDS = 15


class DnsPane(Pane):
    KEYS = ('dns',)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.adapter = None

    def sources(self):
        return [('dns', 'dns_state', (), 1)]

    def render_state(self):
        state = self.app.data('dns') or {}
        adapters = state.get('adapters') or []
        if not any(item['index'] == self.adapter for item in adapters):
            self.adapter = adapters[0]['index'] if adapters else None
        selected = next((item for item in adapters if item['index'] == self.adapter), {})
        self.summary(_tr('tui.classic.dns_state', dns=', '.join(selected.get('dns') or []) or 'DHCP'))
        entries = [('adapter', _tr('tui.classic.adapter', name=selected.get('name') or '—'), self.choose_adapter),
                   ('provider', _tr('tui.classic.set_dns'), self.choose_provider),
                   ('reset', _tr('tui.panes.reset_to_dhcp'), self.reset)]
        trials = state.get('trials') or []
        if trials:
            self.summary(_tr('tui.classic.dns_state', dns=', '.join(selected.get('dns') or []) or 'DHCP') + '\n' +
                         '\n'.join(_tr('tui.panes.dns_trial_on_adapter_rollback_in_s_keep_or_resto', p0=item.get('adapter'),
                                       p1=item.get('provider'), p2=item.get('seconds_left')) for item in trials))
            entries.extend([
                ('keep', _tr('tui.panes.keep'),
                 lambda: self.app.act(_tr('tui.panes.dns_kept'), 'dns_trial_confirm', journal='dns trial-confirm')),
                ('revert', _tr('tui.panes.restore_now'),
                 lambda: self.app.act(_tr('tui.panes.dns_restored'), 'dns_trial_revert', journal='dns trial-revert')),
            ])
        self.menu(entries)

    def choose_adapter(self):
        def selected(value):
            self.adapter = int(value)
            self.render_state()
        self.choose(_tr('tui.panes.adapter'), [(str(item['index']), item.get('name') or str(item['index']))
                    for item in (self.app.data('dns') or {}).get('adapters') or []], selected)

    def choose_provider(self):
        if self.adapter is None:
            return
        adapter = self.adapter
        def chosen(pid):
            self.app.confirm(_tr('tui.panes.set_dns_on_adapter_if_not_confirmed_within_s_the', p0=pid, p1=adapter, p2=TRIAL_SECONDS),
                             lambda: self.app.act(_tr('tui.panes.dns_on_adapter', p0=pid, p1=adapter), 'dns_set_trial', adapter, pid, TRIAL_SECONDS,
                                                  journal=f'dns trial {adapter} {pid}'))
        self.choose(_tr('tui.panes.provider'), [(item['id'], (item.get('name') or item['id']) + ' · ' + ', '.join(item.get('servers') or []))
                    for item in (self.app.data('dns') or {}).get('providers') or []], chosen)

    def reset(self):
        adapter = self.adapter
        if adapter is not None:
            self.app.confirm(_tr('tui.panes.reset_dns_for_adapter_to_automatic_dhcp', p0=adapter),
                             lambda: self.app.act(_tr('tui.panes.reset_dns_for_adapter', p0=adapter), 'dns_reset', adapter, journal=f'dns reset {adapter}'))


class TgPane(Pane):
    KEYS = ('tg', 'tg_stats')

    def sources(self):
        return [('tg_stats', 'tg_stats', (), 2)] if (self.app.data('tg') or {}).get('running') else []

    def render_state(self):
        state = self.app.data('tg') or {}
        self.summary(tag(state.get('running')) + '\n' + (state.get('link') or f"{state.get('host', '—')}:{state.get('port', '—')}"))
        stats = self.app.data('tg_stats')
        if stats and state.get('running'):
            from modules.cli.commands import render
            current = str(self.query_one('#tg-summary', Static).render())
            self.summary(current + '\n' + '\n'.join(render(stats)))
        self.menu([('toggle', _tr('tui.panes.stop') if state.get('running') else _tr('tui.panes.start'),
                    lambda: OverviewPane.toggle(self, 'tg'))])


LOG_LINES = 1000
LOG_FILES = (('winws', 'DPI'), ('proxy', _tr('tui.textual_app.proxy')), ('tg', 'Telegram'))


class LogsPane(Pane):
    BINDINGS = [Binding('end', 'follow', '', show=False, priority=True)]

    def action_follow(self):
        self.query_one(RichLog).scroll_end(animate=False, immediate=True, x_axis=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.log_module, self.log_offset = 'winws', 0

    def compose(self):
        yield Static('', id='logs-summary', markup=False, classes='pane-summary')
        yield RichLog(id='lg-view', max_lines=LOG_LINES, min_width=1, wrap=True, markup=False, highlight=False)

    def render_state(self):
        self.summary(' · '.join(f'{i}. {name}' + (' [*]' if key == self.log_module else '') for i, (key, name) in enumerate(LOG_FILES, 1)))

    def focus_primary(self):
        self.query_one(RichLog).focus()

    def sources(self):
        return [('log:' + self.log_module, self.log_module + '_log', (self.log_offset,), 1)]

    def choose_number(self, number):
        if number > len(LOG_FILES):
            return
        mod = LOG_FILES[number - 1][0]
        if mod != self.log_module:
            self.log_module, self.log_offset = mod, 0
            self.query_one(RichLog).clear()
            self.app.forget('log:' + mod)
            self.render_state()
            self.app.refresh_now(force=True)

    def state_changed(self, keys):
        key = 'log:' + self.log_module
        if not self.is_mounted or key not in keys:
            return
        packet = self.app.data(key) or {}
        if not packet.get('reset') and not packet.get('data'):
            self.log_offset = packet.get('offset', self.log_offset)
            return
        view = self.query_one(RichLog)
        follow = bool(packet.get('reset')) or view.is_vertical_scroll_end
        position = view.scroll_y
        anchor = view.lines[int(position)] if not follow and int(position) < len(view.lines) else None
        if packet.get('reset'):
            view.clear()
        for line in (packet.get('data') or '').splitlines():
            view.write(line, scroll_end=follow)
        if anchor is not None:
            row = next((i for i, line in enumerate(view.lines) if line is anchor), 0)
            view.scroll_to(y=row + position % 1, animate=False, immediate=True)
        self.log_offset = packet.get('offset', self.log_offset)


THEMES = (('system', _tr('tui.panes.system')), ('light', _tr('tui.panes.light')), ('dark', _tr('tui.panes.dark')))


class SettingsPane(Pane):
    KEYS = ('config', 'verified', 'app')

    def sources(self):
        return [('config', 'config_read', (), 5), ('verified', 'config_verified', (), 5)]

    def render_state(self):
        config, verified = self.app.data('config') or {}, self.app.data('verified') or {}
        backup = verified.get('backup')
        detail = backup['checked_at'] + ' · ' + ', '.join(item['domain'] for item in backup['checks']) if backup else _tr('cli.verified.empty')
        self.summary(_tr('tui.verified.title') + ': ' + detail)
        entries = [('theme', _tr('tui.classic.theme', value=config.get('theme', 'system')), self.theme)]
        if 'lang' in config:
            entries.append(('language', _tr('tui.classic.language', value=config.get('lang', 'auto')), self.language))
        entries.append(('verify', _tr('tui.verified.verify'), self.verify))
        if backup:
            entries.append(('restore', _tr('tui.verified.restore'), self.restore))
        self.menu(entries)

    def setting(self, key, value):
        self.app.write_state(_tr('tui.classic.setting', key=key), 'config', 'config_set',
                             lambda config: {**config, key: value}, lambda config: (key, config[key]), journal=f'config set {key} {value}')

    def theme(self):
        self.choose(_tr('tui.panes.chimera_window_theme'), THEMES, lambda value: self.setting('theme', value))

    def language(self):
        self.choose(_tr('tui.classic.language', value=''), [('auto', _tr('tui.settings.language.auto')),
                    ('ru', _tr('tui.settings.language.ru')), ('en', _tr('tui.settings.language.en'))], lambda value: self.setting('lang', value))

    def verify(self):
        def submitted(value):
            selected = list(dict.fromkeys(value.lower().replace(',', ' ').replace(';', ' ').split()))
            def done(result):
                if not result['saved']:
                    self.app.status(result['error'], error=True)
                else:
                    self.app.status(_tr('cli.verified.saved', id=result['backup']['id']))
            self.app.act(_tr('tui.verified.verify'), 'config_verify', selected, after=done)
        self.prompt(_tr('tui.classic.verify_domains'), submitted)

    def restore(self):
        backup = (self.app.data('verified') or {}).get('backup')
        if not backup:
            return
        def preview(result):
            if not result['ok']:
                self.app.status(result.get('error') or '\n'.join(result['errors']), error=True)
                return
            lines = [_tr('tui.verified.confirm', id=backup['id'])]
            lines.extend(item['title'] + ': ' + '; '.join(item['changes']) for item in result['sections'])
            lines.extend(result.get('warnings', []))
            if result.get('requires_admin'):
                lines.append(_tr('msg.backup.admin_required'))
            def done(result):
                if result['errors'] or result['rollback_errors']:
                    self.app.status('\n'.join(result['errors'] + result['rollback_errors']), error=True)
            self.app.confirm('\n'.join(lines), lambda: self.app.act(_tr('tui.verified.restore'), 'config_backup_restore', backup['id'], True, after=done))
        self.app.act(_tr('tui.verified.restore'), 'config_backup_preview', backup['id'], after=preview)
