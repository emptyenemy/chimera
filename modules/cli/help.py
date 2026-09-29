"""Справка chimera: генерируется из таблицы команд (registry), тексты — в каталоге (ключи cli.help.*)."""

from modules.cli.registry import ACTIONS, BY_GROUP, GROUPS, LEVEL_TITLES, Action, Arg
from modules.i18n import LazySeq, t

EXIT_CODE_VALUES = (0, 1, 2, 3)
# (код, описание); описание — на языке пользователя, берётся в момент чтения
EXIT_CODES = LazySeq(lambda: tuple((c, t(f"cli.exit.{c}")) for c in EXIT_CODE_VALUES))


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
    name = a.label + ("…" if a.kind in ("names", "names1", "rest") else "")
    if a.kind == "bool":
        name = "on|off"
    elif a.kind == "choice" and a.choices:
        name = "|".join(a.choices)
    return f"[{name}]" if a.optional or a.kind in ("names", "rest") else f"<{name}>"


def _params(act: Action) -> list[str]:
    rows = []
    for a in act.args:
        label = f"--{a.name}" if a.flag else a.label
        note = a.help + (f" ({', '.join(a.choices)})" if a.choices and a.kind == "choice" and not a.flag else "")
        rows.append(f"  {label:<14} {note}".rstrip())
    return rows


def action_help(act: Action) -> str:
    lines = [f"{usage(act)}", "", act.summary, ""]
    params = _params(act)
    if params:
        lines += [t("cli.help.params")] + params + [""]
    lines += [t("cli.help.level", level=LEVEL_TITLES[act.level]), t("cli.help.ui", ui=act.ui), ""]
    if act.examples:
        lines += [t("cli.help.examples")] + [f"  {e}" for e in act.examples] + [""]
    return "\n".join(lines).rstrip() + "\n"


def _brief(summary: str) -> str:
    """Первое предложение описания (точка внутри слова, вроде Discord.exe, его не обрывает)."""
    end = summary.find(". ")
    return (summary if end < 0 else summary[:end]).rstrip(".")


def group_help(group: str) -> str:
    acts = list(BY_GROUP[group].values())
    if len(acts) == 1 and acts[0].name == "":
        return action_help(acts[0])
    lines = [t("cli.help.group_title", group=group, summary=GROUPS[group]), "", t("cli.help.actions")]
    for act in acts:
        lines.append(f"  {usage(act)[len('chimera '):]:<50} {_brief(act.summary)}")
    lines += ["", t("cli.help.examples")]
    for act in acts:
        lines += [f"  {e}" for e in act.examples[:1]]
    lines += ["", t("cli.help.action_hint", group=group)]
    return "\n".join(lines) + "\n"


def main_help() -> str:
    rows = []
    for group, summary in GROUPS.items():
        acts = list(BY_GROUP[group])
        variants = "" if acts == [""] else " " + "|".join(acts)
        rows.append(f"  {group + variants:<46} {summary}")
    codes = "\n".join(f"  {code}  {text}" for code, text in EXIT_CODES)
    return t("cli.help.main", commands="\n".join(rows), codes=codes)


def all_actions() -> tuple[Action, ...]:
    return ACTIONS
