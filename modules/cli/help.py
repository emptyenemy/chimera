"""Справка chimera: генерируется из таблицы команд (registry), отдельных текстов нет."""

from modules.cli.registry import ACTIONS, BY_GROUP, GROUPS, LEVEL_TITLES, Action, Arg

EXIT_CODES = (
    (0, "успех"),
    (1, "ошибка выполнения (отказ приложения, нет такого объекта, сбой сети)"),
    (2, "неверные аргументы"),
    (3, "Chimera не запущена, старая версия приложения или нет связи"),
)

MAIN_HELP = """\
Chimera — обход блокировок из командной строки.

Использование:
  chimera <команда> [действие] [параметры]
  chimera --window | --browser          открыть окно или вкладку браузера

Команды:
{commands}

Общие параметры (можно ставить в любое место):
  --json           машинный вывод: {{"schema": 1, "ok": …, "command": …, "level": …, "data": …}}
  --show-secrets   показывать ссылки и секреты (по умолчанию скрыты)
  -h, --help       эта справка; `chimera <команда> --help` — справка по команде
  --version        версия

Коды возврата:
{codes}

Подробнее: `chimera docs` (команды, раскладка папок, формат --json).
"""


def usage(act: Action) -> str:
    parts = ["chimera", act.group] + ([act.name] if act.name else [])
    for a in act.args:
        parts.append(_metavar(a))
    return " ".join(parts)


def _metavar(a: Arg) -> str:
    if a.kind == "switch":
        return f"[--{a.name}]"
    if a.flag:
        return f"[--{a.name} <{a.name}>]"
    name = a.name + ("…" if a.kind in ("names", "names1", "rest") else "")
    return f"[{name}]" if a.optional or a.kind in ("names", "rest") else f"<{name}>"


def _params(act: Action) -> list[str]:
    rows = []
    for a in act.args:
        label = f"--{a.name}" if a.flag else a.name
        note = a.help + (f" ({', '.join(a.choices)})" if a.choices and a.kind == "choice" and not a.flag else "")
        rows.append(f"  {label:<14} {note}".rstrip())
    return rows


def action_help(act: Action) -> str:
    lines = [f"{usage(act)}", "", act.summary, ""]
    params = _params(act)
    if params:
        lines += ["Параметры:"] + params + [""]
    lines += [f"Уровень: {LEVEL_TITLES[act.level]}", f"В интерфейсе: {act.ui}", ""]
    if act.examples:
        lines += ["Примеры:"] + [f"  {e}" for e in act.examples] + [""]
    return "\n".join(lines).rstrip() + "\n"


def group_help(group: str) -> str:
    acts = list(BY_GROUP[group].values())
    if len(acts) == 1 and acts[0].name == "":
        return action_help(acts[0])
    lines = [f"chimera {group} — {GROUPS[group]}", "", "Действия:"]
    for act in acts:
        lines.append(f"  {usage(act)[len('chimera '):]:<44} {act.summary.split('.')[0]}")
    lines += ["", "Примеры:"]
    for act in acts:
        lines += [f"  {e}" for e in act.examples[:1]]
    lines += ["", f"Справка по действию: chimera {group} <действие> --help"]
    return "\n".join(lines) + "\n"


def main_help() -> str:
    rows = []
    for group, summary in GROUPS.items():
        acts = list(BY_GROUP[group])
        variants = "" if acts == [""] else " " + "|".join(acts)
        rows.append(f"  {group + variants:<46} {summary}")
    codes = "\n".join(f"  {code}  {text}" for code, text in EXIT_CODES)
    return MAIN_HELP.format(commands="\n".join(rows), codes=codes)


def all_actions() -> tuple[Action, ...]:
    return ACTIONS
