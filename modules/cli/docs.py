"""Документация Chimera, которая живёт в программе и всегда совпадает с её версией.

Всё строится из самого кода: таблицы команд (registry), кодов возврата (help), констант
путей. `chimera docs [тема]` показывает её людям и агентам, `chimera agent-info --json`
даёт машинную сводку, tools/gen_cli_docs.py собирает из тех же данных docs/CLI.md
(и docs/en/CLI.md на английском). Тексты — в каталоге (ключи docs.*), язык берётся из
modules/i18n.py. Инструкции агентам (как себя вести) сюда не входят: они в
skills/chimera/SKILL.md и обновляются независимо от версии программы.
"""

from modules import control, paths
from modules.cli import help as helptext
from modules.cli.registry import ACTIONS, GROUPS, LEVEL_TITLES
from modules.i18n import LazyMap, LazySeq, t
from modules.version import VERSION

# Какие версии скилла (skills/chimera/SKILL.md, поле version) эта версия программы считает
# совместимыми. Границы включительные. Тест сверяет их с версией скилла в репозитории.
SKILL_COMPAT = {"min": "1.0.0", "max": "1.99.99"}

TOPICS = LazyMap(("commands", "layout", "output"), "docs.topic")

# (ключ описания в каталоге, путь от папки программы, kind). kind: edit | generated | secret |
# log | internal | external
LAYOUT_ITEMS = (
    ("config_json", "config.json", "edit"),
    ("lists_txt", "lists/*.txt", "edit"),
    ("strategies_txt", "strategies/*.txt", "generated"),
    ("hostlist_general_user", "strategies/hostlists/list-general-user.txt", "generated"),
    ("ipset_user", "strategies/hostlists/ipset-user.txt", "generated"),
    ("list_exclude_user", "strategies/hostlists/list-exclude-user.txt", "edit"),
    ("ipset_exclude_user", "strategies/hostlists/ipset-exclude-user.txt", "edit"),
    ("ipset_all", "strategies/hostlists/ipset-all.txt", "edit"),
    ("winws_json", "data/winws.json", "internal"),
    ("proxy_json", "data/proxy.json", "secret"),
    ("tgproxy_json", "data/tgproxy.json", "secret"),
    ("hosts_json", "data/hosts.json", "internal"),
    ("dns_user_json", "data/dns_providers.user.json", "internal"),
    ("singbox_config", "data/singbox-config.json", "generated"),
    ("singbox_domains", "data/singbox-domains.json", "generated"),
    ("singbox_ips", "data/singbox-ips.json", "generated"),
    ("proxy_pac", "data/proxy.pac", "generated"),
    ("logs", "data/logs/*.log", "log"),
    ("changes_log", "data/changes.log", "log"),
    ("control_json", "data/control.json", "secret"),
    ("bin", "bin/", "external"),
    ("upstream", "upstream/", "external"),
)
# (путь, kind, описание на текущем языке)
LAYOUT = LazySeq(lambda: tuple((p, k, t(f"docs.layout.{slug}")) for slug, p, k in LAYOUT_ITEMS))

KIND_TITLES = LazyMap(("edit", "generated", "secret", "log", "internal", "external"), "docs.kind")

JSON_FORMAT = LazyMap(("schema", "ok", "command", "level", "data", "error"), "docs.json")

# общие флаги: (ключ в каталоге, как пишется)
GLOBAL_FLAGS = (("json", "--json"), ("show_secrets", "--show-secrets"), ("lang", "--lang"),
                ("help", "-h/--help"), ("version", "--version"))


def commands_data() -> list[dict]:
    rows = []
    for a in ACTIONS:
        rows.append({
            "command": a.command, "group": a.group, "action": a.name, "level": a.level,
            "summary": a.summary, "ui": a.ui, "usage": helptext.usage(a),
            "args": [{"name": x.name, "label": x.label, "kind": x.kind, "help": x.help,
                      "optional": x.optional or x.kind in ("names", "rest"),
                      "flag": x.flag, "choices": list(x.choices)} for x in a.args],
            "examples": list(a.examples), "offline": a.offline, "methods": list(a.api_methods),
        })
    return rows


def layout_data() -> list[dict]:
    return [{"path": p, "kind": k, "note": n} for p, k, n in LAYOUT]


def global_flags() -> dict:
    return {flag: t(f"docs.flag.{key}") for key, flag in GLOBAL_FLAGS}


def output_data() -> dict:
    return {
        "exit_codes": {str(c): text for c, text in helptext.EXIT_CODES},
        "json": dict(JSON_FORMAT),
        "levels": dict(LEVEL_TITLES),
        "secrets": t("docs.secrets"),
        "global_flags": global_flags(),
    }


def paths_data() -> dict:
    from modules import appconfig, domains
    return {"app_dir": str(paths.APP_DIR), "data_dir": str(paths.DATA_DIR), "logs_dir": str(paths.LOG_DIR),
            "config": str(appconfig.CONFIG_PATH), "lists_dir": str(domains.LISTS_DIR),
            "changes_log": str(paths.DATA_DIR / "changes.log"), "control_file": str(control.CONTROL_PATH)}


def all_data() -> dict:
    return {"topics": dict(TOPICS), "commands": commands_data(), "layout": layout_data(), "output": output_data()}


def topic_data(topic: str):
    return {"commands": commands_data, "layout": layout_data, "output": output_data}[topic]()


# --- текст для людей ---------------------------------------------------------------------

def commands_text() -> str:
    out = []
    for group, summary in GROUPS.items():
        out.append(f"{group} — {summary}")
        for a in ACTIONS:
            if a.group != group:
                continue
            out.append(f"  {helptext.usage(a)}")
            out.append(f"      {a.summary}  [{LEVEL_TITLES[a.level]}]")
            for e in a.examples[:2]:
                out.append("      " + t("docs.text.example", example=e))
        out.append("")
    return "\n".join(out).rstrip()


def layout_text() -> str:
    out = [t("docs.text.layout_intro"), ""]
    for p, kind, note in LAYOUT:
        out.append(f"{p}   [{KIND_TITLES[kind]}]")
        out.append(f"    {note}")
    return "\n".join(out)


def output_text() -> str:
    d = output_data()
    out = [t("docs.text.exit_title")] + [f"  {c}  {text}" for c, text in d["exit_codes"].items()]
    out += ["", t("docs.text.json_title")] + [f"  {k}: {v}" for k, v in d["json"].items()]
    out += ["", t("docs.text.levels_title")] + [f"  {k}: {v}" for k, v in d["levels"].items()]
    out += ["", t("docs.text.secrets", text=d["secrets"])]
    return "\n".join(out)


def topic_text(topic: str) -> str:
    return {"commands": commands_text, "layout": layout_text, "output": output_text}[topic]()


def index_text() -> str:
    lines = [t("docs.text.index_title", version=VERSION), ""]
    lines += [f"  chimera docs {name:<9} {desc}" for name, desc in TOPICS.items()]
    lines += ["", t("docs.text.index_hint")]
    return "\n".join(lines)


# --- сводка для агентов ------------------------------------------------------------------------

def agent_info() -> dict:
    return {
        "program": {"version": VERSION, "protocol": control.PROTOCOL},
        "skill_compat": dict(SKILL_COMPAT),
        "levels": dict(LEVEL_TITLES),
        "commands": [{"command": c["command"], "level": c["level"], "summary": c["summary"],
                      "usage": c["usage"], "offline": c["offline"]} for c in commands_data()],
        "paths": paths_data(),
        "exit_codes": output_data()["exit_codes"],
        "docs": {"topics": dict(TOPICS), "command": t("docs.agent_command")},
    }


def agent_info_text() -> str:
    info = agent_info()
    lines = [t("docs.text.info_program", version=info["program"]["version"], protocol=info["program"]["protocol"]),
             t("docs.text.info_skill", min=info["skill_compat"]["min"], max=info["skill_compat"]["max"]),
             t("docs.text.info_commands", count=len(info["commands"]))]
    return "\n".join(lines)


# --- docs/CLI.md ------------------------------------------------------------------------------------

def cli_md() -> str:
    """Человеческая документация для репозитория; тест сверяет закоммиченный файл с этим текстом."""
    L = [t("docs.md.title"), "", t("docs.md.generated"), "", t("docs.md.intro"), "", t("docs.md.intro2"), "",
         t("docs.md.h_flags"), ""]
    for flag, text in output_data()["global_flags"].items():
        L.append(f"- `{flag}` — {text}")
    L += ["", t("docs.md.h_exit"), ""] + [f"- `{c}` — {text}" for c, text in helptext.EXIT_CODES]
    L += ["", t("docs.md.h_json"), "", t("docs.md.json_intro"), ""]
    L += [f"- `{k}` — {v}" for k, v in JSON_FORMAT.items()]
    L += ["", t("docs.md.h_levels"), ""] + [f"- `{k}` — {v}" for k, v in LEVEL_TITLES.items()]
    L += ["", t("docs.md.levels_note"), "",
          t("docs.md.h_parity"), "",
          t("docs.md.th_parity"), "|---|---|---|"]
    for a in ACTIONS:
        L.append(f"| {a.ui} | `{helptext.usage(a)}` | {a.level} |")
    L += ["", t("docs.md.excluded_title"), ""]
    from modules.cli.registry import EXCLUDED
    for method, why in EXCLUDED.items():
        L.append(f"- `{method}` — {why}")
    L += ["", t("docs.md.h_details"), ""]
    for group, summary in GROUPS.items():
        L += [f"### {group}", "", summary[0].upper() + summary[1:] + ".", ""]
        for a in ACTIONS:
            if a.group != group:
                continue
            L += [f"#### `{helptext.usage(a)}`", "",
                  t("docs.md.action_line", summary=a.summary, level=LEVEL_TITLES[a.level])
                  + (t("docs.md.offline") if a.offline else ""), ""]
            for x in a.args:
                label = f"--{x.name}" if x.flag else x.label
                L.append(f"- `{label}` — {x.help or x.kind}")
            if a.args:
                L.append("")
            L += ["```", *a.examples, "```", ""]
    L += [t("docs.md.h_files"), "", t("docs.md.th_files"), "|---|---|"]
    for p, kind, note in LAYOUT:
        L.append(f"| `{p}` | {KIND_TITLES[kind]}: {note} |")
    L += [""]
    return "\n".join(L)
