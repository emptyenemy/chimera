"""Команды CLI через соединение TUI: общий разбор, явный результат и безопасная история."""

import json
import re
import shlex
from dataclasses import dataclass

from modules import control, i18n
from modules.cli import app as cli, commands, help as helptext
from modules.cli.client import CliError, Usage
from modules.cli.registry import Action, READ
from modules.i18n import t
from tui.remote import Offline, RemoteError

PROCESS_HANDLERS = frozenset({'start', 'stop', 'restart', 'tui', 'service', 'path_add', 'path_remove'})
_SENSITIVE = re.compile(r'\b(?:proxy\s+link|tg\s+advanced)\b|--secret(?:\s|=|$)|'
                        r'(?:vless|vmess|trojan|ss|hysteria2|hy2|tuic|tg)://|'
                        r'--(?:s|se|sec|secr|secre)(?:\s|=|$)', re.I)
_OPERATORS = frozenset({'&', '&&', '|', '||', ';', '<', '>', '>>', '2>', '2>>'})


def sensitive(value):
    return bool(_SENSITIVE.search(value.replace('"', '').replace("'", '')))


@dataclass
class Invocation:
    text: str
    action: Action | None = None
    arguments: dict | None = None
    argv: tuple = ()
    lang: str | None = None
    as_json: bool = False
    help: bool = False

    @property
    def changes(self):
        return self.action is not None and not self.help and self.action.level != READ

    @property
    def label(self):
        if self.help:
            return ('help ' + (self.action.command if self.action else ' '.join(self.argv[1:]))).rstrip()
        return commands.loggable(self.action, list(self.argv))


def prepare(value):
    if any((ord(char) < 32 and char not in '\t') or ord(char) == 127 for char in value):
        raise Usage.of('tui.console.invalid_input')
    value = value.strip().lstrip(':').strip()
    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    lexer.escape = ''
    try:
        words = list(lexer)
    except ValueError:
        raise Usage.of('tui.console.quote_error') from None
    if words and words[0].lower() in ('chimera', 'chimera.exe'):
        words.pop(0)
    if _OPERATORS.intersection(words):
        raise Usage.of('tui.console.no_operators')
    if '--show-secrets' in words:
        raise Usage.of('tui.console.hidden_secrets')
    as_json = '--json' in words
    words, lang = cli._take_lang([word for word in words if word != '--json'])
    if words and words[0] == '--version':
        words = ['version', *words[1:]]
    wants_help = not words or words[0] in ('help', '-h', '--help')
    wants_help |= bool(words and words[0] in cli.BY_GROUP and cli._wants_help(words[1:]))
    if wants_help:
        names = [word for word in words if word not in ('help', '-h', '--help')]
        group = names[0] if names and names[0] in cli.BY_GROUP else None
        action = cli.BY_GROUP[group].get(names[1]) if group and len(names) > 1 else None
        return Invocation(value, action, argv=('help', group) if group else ('help',), lang=lang, help=True)
    with i18n.request_language(lang):
        action, rest = cli._resolve(words)
        arguments = cli.parse(action, rest)
    if action.handler in PROCESS_HANDLERS:
        raise Usage.of('tui.console.standalone', command=action.command)
    if action.handler == 'lists_save' and not arguments.get('a1'):
        raise Usage.of('tui.console.editor_hint')
    if action.handler in ('proxy_link', 'config_import', 'config_import_preview') and arguments.get('a0') == '-':
        raise Usage.of('tui.console.no_stdin')
    return Invocation(value, action, arguments, tuple(words), lang, as_json)


class RemoteContext(commands.Ctx):
    def __init__(self, remote, *, as_json=False):
        super().__init__(json=as_json, reveal=False)
        self.remote = remote

    def running(self):
        return True

    def client(self):
        raise RuntimeError('Console commands must use the existing remote connection')

    def call(self, method, *args, reveal=None):
        if method not in control.ALLOWED_METHODS:
            raise CliError.of('msg.modules.control.method_is_not_available_through_the_command_line', 'forbidden', 1, p0=method)
        try:
            return control.redact(self.remote.call(method, *args))
        except Offline as error:
            raise CliError(str(error), 'not_running', 3) from error
        except RemoteError as error:
            cause = error.__cause__
            raise CliError(str(error), 'remote_error', 1, getattr(cause, 'key', None),
                           getattr(cause, 'params', None)) from error

    def call_or_local(self, method, args, local):
        return self.call(method, *args)


def execute(invocation, remote):
    with i18n.request_language(invocation.lang):
        if invocation.help:
            if invocation.action:
                return commands.Result(lines=helptext.action_help(invocation.action).splitlines())
            if len(invocation.argv) > 1:
                group = invocation.argv[1]
                if group in cli.BY_GROUP:
                    return commands.Result(lines=helptext.group_help(group).splitlines())
            return commands.Result(lines=helptext.main_help().splitlines())
        if invocation.action.handler == 'logs':
            module = invocation.arguments['a0']
            tail = invocation.arguments.get('a1')
            tail = commands.LOG_TAIL_DEFAULT if tail is None else tail
            if tail < 1:
                raise Usage.of('tui.console.tail_positive')
            result = RemoteContext(remote).call(module + '_log', 0)
            lines = result.get('data', '').splitlines()[-tail:]
            return commands.Result({'module': module, 'lines': lines}, lines or [t('cli.logs.empty')])
        context = RemoteContext(remote, as_json=invocation.as_json)
        return commands.execute(context, invocation.action, invocation.arguments)


def output(invocation, result):
    with i18n.request_language(invocation.lang):
        if invocation.as_json and not invocation.help:
            return json.dumps({'schema': cli.SCHEMA, 'ok': result.exit_code == 0,
                               'command': invocation.action.command, 'level': invocation.action.level,
                               'data': control.redact(result.data)}, ensure_ascii=False, indent=2).splitlines()
        return result.lines if result.lines is not None else (commands.render(control.redact(result.data)) or [t('cli.done')])


class History:
    def __init__(self, limit=100):
        self.limit = limit
        self.items = []
        self.position = 0
        self.draft = ''

    def add(self, value):
        if value and not sensitive(value) and (not self.items or value != self.items[-1]):
            self.items.append(value)
            self.items = self.items[-self.limit:]
        self.reset()

    def reset(self):
        self.position = len(self.items)
        self.draft = ''

    def move(self, direction, value):
        if self.position == len(self.items):
            self.draft = value
        self.position = max(0, min(len(self.items), self.position + direction))
        return self.items[self.position] if self.position < len(self.items) else self.draft
