"""Точка входа chimera: разбор аргументов, вызов команды, вывод и коды возврата."""

import argparse
import json
import os
import re
import sys

from modules.cli import commands, help as helptext
from modules.cli.client import CliError, Usage
from modules.cli.registry import ACTIONS, BY_GROUP, DEFAULT_ACTION, Action, Arg

SCHEMA = 1
UI_FLAGS = ("--window", "--browser", "--tray")
_ONOFF = {"on": True, "true": True, "1": True, "yes": True, "да": True,
          "off": False, "false": False, "0": False, "no": False, "нет": False}


# --- разбор аргументов ----------------------------------------------------------------------

def _translate(message: str) -> str:
    m = re.match(r"the following arguments are required: (.+)", message)
    if m:
        return f"не указан параметр: {m.group(1)}"
    m = re.match(r"argument [^:]+: invalid choice: '?([^' ]*)'? \(choose from (.+)\)", message)
    if m:
        options = ", ".join(x.strip("' ") for x in m.group(2).split(","))
        return f"недопустимое значение {m.group(1)!r}; допустимо: {options}"
    m = re.match(r"unrecognized arguments: (.+)", message)
    if m:
        return f"лишние параметры: {m.group(1)}"
    m = re.match(r"argument (--[\w-]+): expected one argument", message)
    if m:
        return f"у {m.group(1)} нет значения"
    m = re.match(r"argument [^:]+: (.+)", message)
    return m.group(1) if m else message


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(f"{_translate(message)}. Справка: {self.prog} --help")


def _int(arg: Arg):
    def conv(text):
        try:
            return int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{arg.name}: нужно целое число ({arg.help or arg.name})") from None
    return conv


def _bool(text):
    try:
        return _ONOFF[str(text).strip().lower()]
    except KeyError:
        raise argparse.ArgumentTypeError("нужно on или off") from None


def _value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def build_parser(act: Action) -> argparse.ArgumentParser:
    p = _Parser(prog=f"chimera {act.command}", add_help=False)
    for i, arg in enumerate(act.args):
        dest = f"a{i}"
        conv = {"int": _int(arg), "bool": _bool, "value": _value}.get(arg.kind, str)
        if arg.kind == "switch":
            p.add_argument(f"--{arg.name}", dest=dest, action="store_true", default=False)
        elif arg.flag:
            p.add_argument(f"--{arg.name}", dest=dest, type=conv, default=None,
                           choices=arg.choices or None, metavar=arg.name)
        else:
            kw = {"dest": dest, "metavar": arg.name}
            if arg.kind == "rest":
                kw["nargs"] = argparse.REMAINDER
            elif arg.kind == "names":
                kw["nargs"] = "*"
            elif arg.kind == "names1":
                kw["nargs"] = "+"
            elif arg.optional:
                kw["nargs"] = "?"
            if arg.kind == "choice":
                kw["choices"] = arg.choices
            p.add_argument(type=conv, **kw)
    return p


def parse(act: Action, argv: list[str]) -> dict:
    return vars(build_parser(act).parse_args(argv))


# --- вывод ----------------------------------------------------------------------------------------

def _setup_streams() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w"))
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _emit_json(payload: dict) -> None:
    print(json.dumps({"schema": SCHEMA, **payload}, ensure_ascii=False, indent=2))


def _fail(e: CliError, command: str, as_json: bool) -> int:
    if as_json:
        _emit_json({"ok": False, "command": command, "error": {"code": e.code, "message": e.message}})
    else:
        print(e.message, file=sys.stderr)
    return e.exit_code


# --- основной путь ------------------------------------------------------------------------------------

def _resolve(argv: list[str]) -> tuple[Action, list[str]]:
    group, rest = argv[0], argv[1:]
    if group not in BY_GROUP:
        raise Usage(f"Неизвестная команда {group!r}. Список команд: chimera --help")
    acts = BY_GROUP[group]
    if "" in acts:
        return acts[""], rest
    if rest and rest[0] in acts:
        return acts[rest[0]], rest[1:]
    default = DEFAULT_ACTION.get(group)
    if default and rest and not rest[0].startswith("-"):
        return acts[default], rest
    if not rest:
        raise Usage(f"Укажите действие для {group}: {', '.join(acts)}. Справка: chimera {group} --help")
    raise Usage(f"У команды {group} нет действия {rest[0]!r}. Доступные: {', '.join(acts)}.")


def _wants_help(argv: list[str]) -> bool:
    return any(a in ("-h", "--help") for a in argv)


def _print_help(argv: list[str]) -> None:
    """Справка по тому, что успели назвать: команда, команда и действие или общая."""
    words = [a for a in argv if a not in ("-h", "--help", "help")]
    if not words or words[0] not in BY_GROUP:
        print(helptext.main_help(), end="")
        return
    group, rest = words[0], words[1:]
    acts = BY_GROUP[group]
    if rest and rest[0] in acts:
        print(helptext.action_help(acts[rest[0]]), end="")
    else:
        print(helptext.group_help(group), end="")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _setup_streams()
    as_json = "--json" in argv
    reveal = "--show-secrets" in argv
    argv = [a for a in argv if a not in ("--json", "--show-secrets")]
    command = " ".join(a for a in argv if not a.startswith("-"))[:60]

    try:
        if not argv:
            print(helptext.main_help(), end="")
            return 0
        if argv[0] in ("-h", "--help", "help"):
            _print_help(argv)
            return 0
        if argv[0] == "--version":
            argv = ["version"]
        if argv[0] in BY_GROUP and _wants_help(argv[1:]):
            _print_help(argv)
            return 0
        act, rest = _resolve(argv)
        command = act.command
        ns = parse(act, rest)
        ctx = commands.Ctx(json=as_json, reveal=reveal)
        try:
            result = commands.execute(ctx, act, ns)
        except CliError:
            commands.record_change(act, argv, False)
            raise
        commands.record_change(act, argv, result.exit_code == 0)
        if as_json:
            _emit_json({"ok": result.exit_code == 0, "command": act.command, "level": act.level,
                        "data": result.data})
        else:
            lines = result.lines if result.lines is not None else (commands.render(result.data) or ["Готово."])
            for line in lines:
                print(line)
        return result.exit_code
    except CliError as e:
        return _fail(e, command, as_json)
    except KeyboardInterrupt:
        return _fail(CliError("Прервано.", "interrupted", 1), command, as_json)


def all_actions() -> tuple[Action, ...]:
    return ACTIONS
