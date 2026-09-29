"""Документация Chimera, которая живёт в программе и всегда совпадает с её версией.

Всё строится из самого кода: таблицы команд (registry), кодов возврата (help), констант
путей. `chimera docs [тема]` показывает её людям и агентам, `chimera agent-info --json`
даёт машинную сводку, tools/gen_cli_docs.py собирает из тех же данных docs/CLI.md.
Инструкции агентам (как себя вести) сюда не входят: они в skills/chimera/SKILL.md и
обновляются независимо от версии программы.
"""

from modules import control, paths
from modules.cli import help as helptext
from modules.cli.registry import ACTIONS, GROUPS, LEVEL_TITLES
from modules.version import VERSION

# Какие версии скилла (skills/chimera/SKILL.md, поле version) эта версия программы считает
# совместимыми. Границы включительные. Тест сверяет их с версией скилла в репозитории.
SKILL_COMPAT = {"min": "1.0.0", "max": "1.99.99"}

TOPICS = {
    "commands": "все команды с уровнями и примерами",
    "layout": "папки и файлы: что редактируется, что генерируется, что секрет",
    "output": "коды возврата, формат --json, уровни и секреты",
}

# path — от папки программы. kind: edit | generated | secret | log | internal | external
LAYOUT = (
    ("config.json", "edit", "Настройки программы. Менять командой `chimera config set` (часть ключей — только правкой файла)."),
    ("lists/*.txt", "edit", "Списки доменов и подсетей, по одной записи в строке, # — комментарий. Команды `chimera lists …`. "
     "Правку файла напрямую работающая программа подхватывает сама за пару секунд (создание, изменение, удаление); "
     "проверить файл: `chimera lists validate`."),
    ("strategies/*.txt", "generated", "Стратегии winws2, портируются из Flowseal (tools/port_flowseal.py). Не править."),
    ("strategies/hostlists/list-general-user.txt", "generated", "Собирается из выбранных у обхода списков. Не править."),
    ("strategies/hostlists/ipset-user.txt", "generated", "Подсети из выбранных списков. Не править."),
    ("strategies/hostlists/list-exclude-user.txt", "edit", "Домены-исключения для обхода. Править только по просьбе пользователя."),
    ("strategies/hostlists/ipset-exclude-user.txt", "edit", "Подсети-исключения для обхода. Править только по просьбе пользователя."),
    ("strategies/hostlists/ipset-all.txt", "edit", "Общий список подсетей (режим ipset). Меняется командами `chimera winws ipset …`."),
    ("data/winws.json", "internal", "Последняя стратегия, выбранные списки, автозапуск обхода. Менять командами `chimera winws …`."),
    ("data/proxy.json", "secret", "Ссылка прокси (учётные данные), режим, списки, приложения. Не читать и не показывать."),
    ("data/tgproxy.json", "secret", "Порт, секрет и параметры Telegram-прокси. Не читать и не показывать."),
    ("data/hosts.json", "internal", "Привязки списков к провайдерам hosts, фоновые опции. Команды `chimera hosts …`."),
    ("data/dns_providers.user.json", "internal", "DNS-провайдеры, добавленные пользователем. Команды `chimera dns provider-…`."),
    ("data/singbox-config.json", "generated", "Конфиг sing-box. Пересобирается программой."),
    ("data/singbox-domains.json", "generated", "Домены выбранных у прокси списков (файл правил sing-box). Пересобирается."),
    ("data/singbox-ips.json", "generated", "Подсети выбранных у прокси списков. Пересобирается."),
    ("data/proxy.pac", "generated", "PAC-файл режима pac. Пересобирается."),
    ("data/logs/*.log", "log", "Логи модулей (winws, proxy, tgproxy, hosts, service, update). Читать: `chimera logs <модуль>`."),
    ("data/changes.log", "log", "Журнал изменений: время, источник (`cli` — команда, `file` — правка списка "
     "на диске), команда, результат (`ok` или `error`)."),
    ("data/control.json", "secret", "Порт и токен канала управления. Агенту читать не нужно, не показывать."),
    ("bin/", "external", "Бинарники (sing-box, winws2). Не править."),
    ("upstream/", "external", "Внешние проекты (сабмодули). Не править."),
)

KIND_TITLES = {"edit": "можно править", "generated": "генерируется, не править", "secret": "секрет",
               "log": "лог, только читать", "internal": "внутреннее состояние", "external": "внешнее, не править"}

JSON_FORMAT = {
    "schema": "версия формата вывода (сейчас 1); растёт только при несовместимых изменениях",
    "ok": "true/false — успех команды",
    "command": "команда без параметров, например `winws start`",
    "level": "read | app | system — что команда меняет (только при ok=true)",
    "data": "то, что вернул метод приложения, без потерь; у составных команд (status, check) — сводка",
    "error": "при ok=false: {code, message}; code — usage, not_running, app_too_old, remote_error, forbidden, …",
}


def commands_data() -> list[dict]:
    rows = []
    for a in ACTIONS:
        rows.append({
            "command": a.command, "group": a.group, "action": a.name, "level": a.level,
            "summary": a.summary, "ui": a.ui, "usage": helptext.usage(a),
            "args": [{"name": x.name, "kind": x.kind, "help": x.help, "optional": x.optional or x.kind in ("names", "rest"),
                      "flag": x.flag, "choices": list(x.choices)} for x in a.args],
            "examples": list(a.examples), "offline": a.offline, "methods": list(a.api_methods),
        })
    return rows


def layout_data() -> list[dict]:
    return [{"path": p, "kind": k, "note": n} for p, k, n in LAYOUT]


def output_data() -> dict:
    return {
        "exit_codes": {str(c): t for c, t in helptext.EXIT_CODES},
        "json": JSON_FORMAT,
        "levels": dict(LEVEL_TITLES),
        "secrets": "ссылка прокси и секрет Telegram-прокси скрыты; `--show-secrets` показывает их (только по просьбе пользователя)",
        "global_flags": {"--json": "машинный вывод", "--show-secrets": "не скрывать секреты", "-h/--help": "справка",
                         "--version": "версия"},
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
                out.append(f"      пример: {e}")
        out.append("")
    return "\n".join(out).rstrip()


def layout_text() -> str:
    out = ["Пути даны от папки программы.", ""]
    for p, kind, note in LAYOUT:
        out.append(f"{p}   [{KIND_TITLES[kind]}]")
        out.append(f"    {note}")
    return "\n".join(out)


def output_text() -> str:
    d = output_data()
    out = ["Коды возврата:"] + [f"  {c}  {t}" for c, t in d["exit_codes"].items()]
    out += ["", "Формат --json (объект):"] + [f"  {k}: {v}" for k, v in d["json"].items()]
    out += ["", "Уровни команд:"] + [f"  {k}: {v}" for k, v in d["levels"].items()]
    out += ["", "Секреты: " + d["secrets"]]
    return "\n".join(out)


def topic_text(topic: str) -> str:
    return {"commands": commands_text, "layout": layout_text, "output": output_text}[topic]()


def index_text() -> str:
    lines = ["Документация Chimera, версия " + VERSION, ""]
    lines += [f"  chimera docs {name:<9} {desc}" for name, desc in TOPICS.items()]
    lines += ["", "Машинный вид: chimera docs --json, chimera agent-info --json"]
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
        "docs": {"topics": dict(TOPICS), "command": "chimera docs [тема]"},
    }


def agent_info_text() -> str:
    info = agent_info()
    lines = [f"Chimera {info['program']['version']}, протокол командной строки {info['program']['protocol']}",
             f"Совместимые версии скилла: {info['skill_compat']['min']} … {info['skill_compat']['max']}",
             f"Команд: {len(info['commands'])}. Подробно: chimera docs commands, машинный вид: --json."]
    return "\n".join(lines)


# --- docs/CLI.md ------------------------------------------------------------------------------------

def cli_md() -> str:
    """Человеческая документация для репозитория; тест сверяет закоммиченный файл с этим текстом."""
    L = ["# Командная строка chimera", "",
         "<!-- Файл сгенерирован: python tools/gen_cli_docs.py. Руками не править — правьте modules/cli/registry.py. -->", "",
         "Всё, что делается в интерфейсе Chimera, делается командой `chimera …`. Справка встроена: "
         "`chimera --help`, `chimera <команда> --help`, `chimera docs`.", "",
         "Запуск без аргументов из терминала печатает справку; двойной клик по `Chimera.exe` открывает окно. "
         "`chimera --window` и `chimera --browser` открывают окно или вкладку браузера.", "",
         "## Общие параметры", ""]
    for flag, text in output_data()["global_flags"].items():
        L.append(f"- `{flag}` — {text}")
    L += ["", "## Коды возврата", ""] + [f"- `{c}` — {t}" for c, t in helptext.EXIT_CODES]
    L += ["", "## Формат `--json`", "", "Вывод — один объект:", ""]
    L += [f"- `{k}` — {v}" for k, v in JSON_FORMAT.items()]
    L += ["", "## Уровни команд", ""] + [f"- `{k}` — {v}" for k, v in LEVEL_TITLES.items()]
    L += ["", "Уровни нужны, чтобы ограничивать удалённые каналы. Секреты (ссылка прокси, секрет Telegram-прокси) "
          "в выводе скрыты; `--show-secrets` показывает их.", "",
          "## Что в интерфейсе — какая команда", "",
          "| В интерфейсе | Команда | Уровень |", "|---|---|---|"]
    for a in ACTIONS:
        L.append(f"| {a.ui} | `{helptext.usage(a)}` | {a.level} |")
    L += ["", "Не превращены в команды (с причинами):", ""]
    from modules.cli.registry import EXCLUDED
    for method, why in EXCLUDED.items():
        L.append(f"- `{method}` — {why}")
    L += ["", "## Команды подробно", ""]
    for group, summary in GROUPS.items():
        L += [f"### {group}", "", summary[0].upper() + summary[1:] + ".", ""]
        for a in ACTIONS:
            if a.group != group:
                continue
            L += [f"#### `{helptext.usage(a)}`", "", f"{a.summary} Уровень: {LEVEL_TITLES[a.level]}."
                  + (" Работает и без запущенной Chimera." if a.offline else ""), ""]
            for x in a.args:
                label = f"--{x.name}" if x.flag else x.name
                L.append(f"- `{label}` — {x.help or x.kind}")
            if a.args:
                L.append("")
            L += ["```", *a.examples, "```", ""]
    L += ["## Файлы", "", "| Путь | Что это |", "|---|---|"]
    for p, kind, note in LAYOUT:
        L.append(f"| `{p}` | {KIND_TITLES[kind]}: {note} |")
    L += [""]
    return "\n".join(L)
