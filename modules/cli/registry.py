"""Таблица команд chimera: что делается в интерфейсе — какой командой.

Единственный источник для всего, что описывает CLI: справка (`chimera <команда> --help`),
разбор аргументов, набор методов Api, разрешённых по каналу управления, таблица
паритета в docs/CLI.md и references/cli.md у скилла (tools/gen_cli_docs.py).
Каждое действие интерфейса, у которого есть метод Api, обязано быть здесь или в EXCLUDED
с причиной: это проверяет tests/test_cli_parity.py.

Уровни (нужны, чтобы позже ограничивать удалённые каналы — страницу для телефона и
встроенного помощника):
  read   — только чтение, ничего не меняет;
  app    — меняет настройки и состояние самой Chimera;
  system — меняет систему: запуск обхода, hosts, DNS, TUN, обновление, автозапуск.

Все человекочитаемые тексты (описания команд и параметров, «где в интерфейсе», названия
групп и уровней) лежат в каталогах modules/locales под ключами cli.*; здесь только
устройство таблицы. Ключи: cli.cmd.<группа>[.<действие>].summary | .ui | .arg.<параметр>,
cli.group.<группа>, cli.level.<уровень>, cli.excluded.<метод>, cli.argname.<параметр>.
"""

from dataclasses import dataclass, replace

from modules.i18n import LazyMap, has, t

READ, APP, SYSTEM = "read", "app", "system"
LEVEL_TITLES = LazyMap((READ, APP, SYSTEM), "cli.level")

# Имена позиционных параметров по-русски (`chimera winws start [стратегия]`) остаются
# стабильными идентификаторами в --json; в каталоге им соответствуют латинские ключи.
ARG_SLUGS = {
    "значение": "value", "имя": "name", "стратегия": "strategy", "списки": "lists", "режим": "mode",
    "слот": "slot", "блоб": "blob", "ссылка": "link", "приложения": "apps", "настройки": "settings",
    "привязки": "bindings", "серверы": "servers", "адаптер": "adapter", "провайдер": "provider",
    "файл": "file", "домены": "domains", "старое": "old", "новое": "new", "домен": "domain",
    "список": "list", "модуль": "module", "команда": "command", "параметры": "params", "тема": "topic",
    "ключ": "key", "язык": "language",
}


@dataclass(frozen=True)
class Arg:
    name: str
    kind: str = "str"        # str | int | bool | names | names1 | value | choice | switch
    optional: bool = False
    choices: tuple = ()
    flag: bool = False       # --имя значение, а не позиционный параметр
    default: object = None   # что уйти в Api, если не указано
    cmd: str = ""            # ключ действия в каталоге; проставляет _a

    @property
    def slug(self) -> str:
        return ARG_SLUGS.get(self.name, self.name)

    @property
    def label(self) -> str:
        """Имя параметра на языке пользователя (в справке и сообщениях об ошибках)."""
        return self.name if self.name.isascii() else t(f"cli.argname.{self.slug}")

    @property
    def help(self) -> str:
        key = f"cli.cmd.{self.cmd}.arg.{self.slug}"
        return t(key) if has(key) else ""


@dataclass(frozen=True)
class Action:
    group: str
    name: str                # "" — у группы одно действие (chimera status)
    method: str | None = None
    methods: tuple = ()      # если действие составное и зовёт несколько методов Api
    args: tuple = ()
    fixed: tuple = ()        # аргументы, которые команда подставляет сама (hosts on → True)
    level: str = READ
    examples: tuple = ()
    handler: str | None = None
    offline: bool = False    # работает и без запущенной Chimera

    @property
    def key(self) -> str:
        return f"{self.group}.{self.name}" if self.name else self.group

    @property
    def summary(self) -> str:
        return t(f"cli.cmd.{self.key}.summary")

    @property
    def ui(self) -> str:
        """Где это в интерфейсе (для таблицы паритета)."""
        return t(f"cli.cmd.{self.key}.ui")

    @property
    def command(self) -> str:
        return f"{self.group} {self.name}".strip()

    @property
    def api_methods(self) -> tuple:
        return tuple(self.methods) + ((self.method,) if self.method else ())


GROUPS = LazyMap((
    "status", "start", "tui", "stop", "restart", "version", "update", "autostart", "discord", "sources", "config",
    "lang", "winws", "proxy", "tg", "hosts", "dns", "panic", "doctor", "lists", "check", "logs", "service",
    "path", "docs", "agent-info", "trial", "explain"), "cli.group")

# Что не превращается в команду и почему. Тест паритета падает на любом публичном методе
# Api, которого нет ни в таблице действий, ни здесь.
EXCLUDED = LazyMap((
    "dispatch", "shutdown", "app_elevate", "open_url", "tg_open_link", "hub_snapshot", "hub_watch", "hub_refresh",
    "block_check_start", "chebur_check_start"), "cli.excluded")

ONOFF = Arg("значение", "bool")


def _a(group, name, method=None, args=(), level=READ, examples=(), handler=None,
       offline=False, methods=(), fixed=()):
    cmd = f"{group}.{name}" if name else group
    args = tuple(replace(x, cmd=cmd) for x in args)
    return Action(group, name, method, tuple(methods), args, tuple(fixed), level, tuple(examples), handler, offline)


ACTIONS: tuple[Action, ...] = (
    # --- приложение ---------------------------------------------------------------------
    _a("explain", "", handler="explain", methods=('route_explain',), level=READ,
       args=(Arg('домен', 'str'), Arg('app', 'str', optional=True, flag=True)),
       examples=('chimera explain youtube.com', 'chimera explain 192.168.1.1 --app chrome.exe',
                 'chimera explain discord.com --app Discord.exe --json')),
    _a("status", "", handler="status", level=READ,
       methods=("app_info", "winws_state", "proxy_state", "tg_state", "hosts_state"),
       examples=("chimera status", "chimera status --json")),
    _a("version", "", handler="version", offline=True,
       examples=("chimera --version", "chimera version --json")),
    _a("start", "", handler="start", level=APP, examples=("chimera start",)),
    _a("tui", "", handler="tui", level=APP, offline=True,
       args=(Arg("simple", "switch", flag=True, default=False),),
       examples=("chimera tui", "chimera tui --simple")),
    _a("stop", "", handler="stop", level=APP, examples=("chimera stop",)),
    _a("restart", "", handler="restart", level=APP, examples=("chimera restart",)),
    _a("update", "state", "selfupdate_state", examples=("chimera update state",)),
    _a("update", "check", "selfupdate_check", examples=("chimera update check",)),
    _a("update", "install", "selfupdate_install", level=SYSTEM,
       examples=("chimera update check && chimera update install",)),
    _a("autostart", "state", "autostart_get", examples=("chimera autostart state",)),
    _a("autostart", "set", "autostart_set", (ONOFF,), SYSTEM,
       ("chimera autostart set on",)),
    _a("discord", "clear-cache", "discord_clear_cache", level=APP,
       examples=("chimera discord clear-cache",)),
    _a("sources", "versions", "upstream_versions", examples=("chimera sources versions",)),
    _a("sources", "check", handler="sources_check",
       methods=("upstream_check_updates", "upstream_check_one"),
       args=(Arg("имя", "str", optional=True),),
       examples=("chimera sources check", "chimera sources check zapret2")),
    _a("sources", "update", "upstream_update",
       (Arg("имя", "str"),), SYSTEM,
       ("chimera sources update zapret2",)),
    _a("config", "get", handler="config_get", methods=("config_read",), offline=True,
       args=(Arg("ключ", "str", optional=True),),
       examples=("chimera config get", "chimera config get update_channel")),
    _a("config", "set", handler="config_set", methods=("config_set",), level=APP,
       offline=True, args=(Arg("ключ", "str"), Arg("значение", "value")),
       examples=("chimera config set update_channel beta", "chimera config set close_to_tray false",
                 "chimera config set theme dark")),
    _a("lang", "show", handler="lang_show", methods=("lang_get",), offline=True,
       examples=("chimera lang show", "chimera lang show --json")),
    _a("lang", "set", handler="lang_set", methods=("config_set",), level=APP, offline=True,
       args=(Arg("значение", "choice", choices=("auto", "ru", "en")),),
       examples=("chimera lang set en", "chimera lang set auto")),
    _a("lang", "catalog", handler="lang_catalog", methods=("i18n_get",), offline=True,
       args=(Arg("язык", "choice", optional=True, choices=("ru", "en")),),
       examples=("chimera lang catalog en --json",)),

    # --- пробное применение ----------------------------------------------------------
    _a("trial", "state", "trial_state", examples=("chimera trial state --json",)),
    _a("trial", "start", handler="trial_start", methods=("trial_start",), level=SYSTEM,
       args=(Arg("kind", "choice", choices=("strategy", "hosts", "tun")), Arg("target", "str"),
             Arg("seconds", "int", flag=True, default=60), Arg("domains", "str", flag=True, default=None)),
       examples=("chimera trial start strategy general --seconds 60 --domains example.com,discord.com",
                 "chimera trial start hosts on", "chimera trial start tun tun")),
    _a("trial", "confirm", "trial_confirm", args=(Arg("id", "str"),), level=APP,
       examples=("chimera trial confirm 0123456789abcdef",)),
    _a("trial", "revert", "trial_revert", args=(Arg("id", "str"),), level=SYSTEM,
       examples=("chimera trial revert 0123456789abcdef",)),

    # --- обход DPI ------------------------------------------------------------------
    _a("winws", "state", "winws_state", examples=("chimera winws state",)),
    _a("winws", "strategies", handler="winws_strategies", methods=("winws_state",),
       examples=("chimera winws strategies --json",)),
    _a("winws", "start", handler="winws_start",
       methods=("winws_state", "winws_start"),
       args=(Arg("стратегия", "str", optional=True),),
       level=SYSTEM, examples=("chimera winws start", "chimera winws start alt2")),
    _a("winws", "stop", "winws_stop", level=SYSTEM,
       examples=("chimera winws stop",)),
    _a("winws", "autostart", "winws_set_autostart", (ONOFF,), APP, ("chimera winws autostart on",)),
    _a("winws", "lists", "winws_set_lists",
       (Arg("списки", "names", optional=True),), APP,
       ("chimera winws lists youtube discord",)),
    _a("winws", "filters", "filters_state", examples=("chimera winws filters",)),
    _a("winws", "game", "game_filter_set",
       (Arg("режим", "choice", choices=("off", "all", "tcp", "udp")),
        Arg("tcp", "str", optional=True, flag=True),
        Arg("udp", "str", optional=True, flag=True)), SYSTEM,
       ("chimera winws game udp", "chimera winws game all --tcp 1024-65535")),
    _a("winws", "ipset", "ipset_set",
       (Arg("режим", "choice", choices=("none", "any", "loaded")),), APP,
       ("chimera winws ipset loaded",)),
    _a("winws", "ipset-update", "ipset_update", level=SYSTEM, examples=("chimera winws ipset-update",)),
    _a("winws", "fake", "fake_set",
       (Arg("слот", "str"), Arg("блоб", "str")), APP,
       ("chimera winws fake discord quic_initial_www_google_com",)),

    # --- прокси ---------------------------------------------------------------------
    _a("proxy", "state", "proxy_state", examples=("chimera proxy state",)),
    _a("proxy", "start", "proxy_start",
       level=SYSTEM, examples=("chimera proxy start",)),
    _a("proxy", "stop", "proxy_stop", level=SYSTEM,
       examples=("chimera proxy stop",)),
    _a("proxy", "mode", "proxy_set_mode",
       (Arg("режим", "choice", choices=("pac", "split", "tun")),), SYSTEM,
       ("chimera proxy mode pac",)),
    _a("proxy", "link", handler="proxy_link",
       methods=("proxy_set_link",), level=APP,
       args=(Arg("ссылка", "str", optional=True), Arg("clear", "switch", flag=True)),
       examples=("chimera proxy link vless://...", "echo vless://... | chimera proxy link -", "chimera proxy link --clear")),
    _a("proxy", "lists", "proxy_set_lists", (Arg("списки", "names", optional=True),), APP,
       ("chimera proxy lists youtube telegram",)),
    _a("proxy", "apps", "proxy_set_apps", (Arg("приложения", "names", optional=True),), APP,
       ("chimera proxy apps Discord.exe chrome.exe",)),
    _a("proxy", "apps-running", "proxy_apps_snapshot", examples=("chimera proxy apps-running",)),
    _a("proxy", "autostart", "proxy_set_autostart", (ONOFF,), APP, ("chimera proxy autostart on",)),
    _a("proxy", "core-download", "proxy_download_core", level=APP, examples=("chimera proxy core-download",)),

    # --- Telegram-прокси --------------------------------------------------------------
    _a("tg", "state", "tg_state", examples=("chimera tg state",)),
    _a("tg", "start", "tg_start", level=APP,
       examples=("chimera tg start",)),
    _a("tg", "stop", "tg_stop", level=APP,
       examples=("chimera tg stop",)),
    _a("tg", "stats", "tg_stats",
       examples=("chimera tg stats",)),
    _a("tg", "link", handler="tg_link", methods=("tg_state",),
       examples=("chimera tg link",)),
    _a("tg", "config", handler="tg_config", methods=("tg_state", "tg_set_config"), level=APP,
       args=(Arg("host", "str", optional=True, flag=True),
             Arg("port", "int", optional=True, flag=True),
             Arg("secret", "str", optional=True, flag=True),
             Arg("autostart", "bool", optional=True, flag=True)),
       examples=("chimera tg config --port 1443", "chimera tg config --host 0.0.0.0")),
    _a("tg", "regen-secret", "tg_regen_secret", level=APP, examples=("chimera tg regen-secret",)),
    _a("tg", "advanced", handler="tg_advanced", methods=("tg_set_advanced",), level=APP,
       args=(Arg("настройки", "names1"),),
       examples=("chimera tg advanced fake_tls_domain=example.com", "chimera tg advanced fallback_cfproxy=false")),
    _a("tg", "check-update", "tg_check_update", examples=("chimera tg check-update",)),

    # --- hosts ------------------------------------------------------------------------
    _a("hosts", "state", "hosts_state", examples=("chimera hosts state",)),
    _a("hosts", "overview", "hosts_overview", examples=("chimera hosts overview --json",)),
    _a("hosts", "on", "hosts_set_enabled", level=SYSTEM, fixed=(True,),
       examples=("chimera hosts on",)),
    _a("hosts", "off", "hosts_set_enabled", level=SYSTEM, fixed=(False,),
       examples=("chimera hosts off",)),
    _a("hosts", "assign", handler="hosts_assign", methods=("hosts_state", "hosts_set_assignments"),
       level=SYSTEM, args=(Arg("привязки", "names", optional=True),
                           Arg("replace", "switch", flag=True)),
       examples=("chimera hosts assign comss=youtube,discord", "chimera hosts assign xbox=")),
    _a("hosts", "provider-add", "hosts_add_provider",
       (Arg("имя", "str"), Arg("doh", "str"), Arg("серверы", "names1")), APP,
       ("chimera hosts provider-add my https://dns.example/dns-query 1.2.3.4",)),
    _a("hosts", "provider-delete",
       "hosts_delete_provider", (Arg("id", "str"),), APP, ("chimera hosts provider-delete my",)),
    _a("hosts", "ping",
       "hosts_ping_one", (Arg("id", "str"),), examples=("chimera hosts ping comss",)),
    _a("hosts", "background", handler="hosts_background", methods=("hosts_set_background", "hosts_overview"),
       level=APP, args=(Arg("настройки", "names", optional=True),),
       examples=("chimera hosts background", "chimera hosts background refresh_enabled=true refresh_interval=21600",
                 "chimera hosts background check_enabled=true check_interval=900")),

    # --- DNS --------------------------------------------------------------------------
    _a("dns", "state", "dns_state",
       examples=("chimera dns state",)),
    _a("dns", "ping",
       handler="dns_ping", methods=("dns_ping", "dns_ping_one"),
       args=(Arg("id", "str", optional=True),), examples=("chimera dns ping",)),
    _a("dns", "probe", "dns_probe", (Arg("id", "str"),),
       examples=("chimera dns probe cloudflare",)),
    _a("dns", "probe-config", handler="dns_probe_config", methods=("dns_probe_config", "dns_set_probe_config"),
       level=APP, args=(Arg("bypass", "str", optional=True, flag=True),
                        Arg("ad", "str", optional=True, flag=True)),
       examples=("chimera dns probe-config", "chimera dns probe-config --bypass rutracker.org")),
    _a("dns", "set", "dns_set",
       (Arg("адаптер", "int"), Arg("провайдер", "str")),
       SYSTEM, ("chimera dns set 12 cloudflare",)),
    _a("dns", "reset", "dns_reset",
       (Arg("адаптер", "int"),), SYSTEM, ("chimera dns reset 12",)),
    _a("dns", "provider-add", "dns_add_provider",
       (Arg("имя", "str"), Arg("серверы", "names1"),
        Arg("ipv6", "str", optional=True, flag=True, default=""),
        Arg("doh", "str", optional=True, flag=True, default=""),
        Arg("dot", "str", optional=True, flag=True, default=""),
        Arg("unblock", "switch", flag=True, default=False),
        Arg("filtering", "switch", flag=True, default=False)), APP,
       ("chimera dns provider-add my 9.9.9.9 149.112.112.112 --doh https://dns.quad9.net/dns-query",)),
    _a("dns", "provider-delete", "dns_delete_provider",
       (Arg("id", "str"),), APP, ("chimera dns provider-delete my",)),

    _a("dns", "trial", "dns_set_trial",
       (Arg("адаптер", "int"), Arg("провайдер", "str"),
        Arg("seconds", "int", optional=True, flag=True, default=15)), SYSTEM,
       ("chimera dns trial 12 cloudflare", "chimera dns trial 12 cloudflare --seconds 30")),
    _a("dns", "trial-confirm", "dns_trial_confirm",
       (Arg("адаптер", "int", optional=True),), APP,
       ("chimera dns trial-confirm 12",)),
    _a("dns", "trial-revert", "dns_trial_revert",
       (Arg("адаптер", "int", optional=True),), SYSTEM,
       ("chimera dns trial-revert 12",)),
    _a("dns", "record-start", "dns_record_start",
       level=APP, examples=("chimera dns record-start",)),
    _a("dns", "record-stop", "dns_record_stop", level=APP,
       examples=("chimera dns record-start", "chimera dns record-stop --json")),

    _a("panic", "", "panic_all", level=SYSTEM, examples=("chimera panic",)),

    _a("doctor", "", handler="doctor", methods=("doctor_run", "doctor_report"),
       args=(Arg("report", "switch", flag=True, default=False),),
       examples=("chimera doctor", "chimera doctor --report", "chimera doctor --json")),

    _a("config", "export", handler="config_export",
       methods=("config_export",),
       args=(Arg("sections", "str", optional=True, flag=True),
             Arg("file", "str", optional=True, flag=True)),
       examples=("chimera config export --file my.chimera", "chimera config export --sections proxy,lists")),
    _a("config", "import-preview",
       handler="config_import_preview", methods=("config_import_preview",),
       args=(Arg("файл", "str"),),
       examples=("chimera config import-preview friend.chimera",)),
    _a("config", "import",
       handler="config_import", methods=("config_import_apply", "config_import_preview"),
       args=(Arg("файл", "str"),
             Arg("sections", "str", optional=True, flag=True),
             Arg("confirm", "switch", flag=True, default=False)),
       level=APP, examples=("chimera config import friend.chimera --sections proxy,lists",)),

    _a("config", "appearance", "appearance_state", examples=("chimera config appearance --json",)),
    _a("config", "appearance-preview", "appearance_preview", args=(Arg("settings", "value"),),
       examples=('chimera config appearance-preview \'{"theme":"dark","appearance":{"palette":"dracula"}}\' --json',)),
    _a("config", "appearance-apply", "appearance_apply", args=(Arg("settings", "value"),), level=APP,
       examples=('chimera config appearance-apply \'{"appearance":{"radius":"rounded"}}\'',)),
    _a("config", "appearance-refresh", "appearance_refresh", level=APP, examples=("chimera config appearance-refresh",)),
    _a("config", "backup", handler="config_backup", methods=("config_backup_create",), level=APP,
       examples=("chimera config backup", "chimera config backup --json")),
    _a("config", "verify", handler="config_verify", methods=("config_verify",), level=APP,
       args=(Arg("домены", "names1"),), examples=("chimera config verify youtube.com,discord.com",)),
    _a("config", "verified", handler="config_verified", methods=("config_verified",),
       examples=("chimera config verified --json",)),
    _a("config", "backups", handler="config_backups", methods=("config_backups",),
       examples=("chimera config backups", "chimera config backups --json")),
    _a("config", "compare", handler="config_compare", methods=("config_backup_compare",),
       args=(Arg("first", "str"), Arg("second", "str")),
       examples=("chimera config compare 20260930-120000-001-manual 20260930-130000-001-manual --json",)),
    _a("config", "restore-preview", handler="config_restore_preview", methods=("config_backup_preview",),
       args=(Arg("id", "str"),), examples=("chimera config restore-preview 20260930-120000-001-import",)),
    _a("config", "restore", handler="config_restore", methods=("config_backup_restore",),
       args=(Arg("id", "str"), Arg("confirm", "switch", flag=True, default=False)), level=SYSTEM,
       examples=("chimera config restore 20260930-120000-001-import --confirm",)),

    # --- списки ----------------------------------------------------------------------
    _a("lists", "show", handler="lists_show", methods=("lists_all", "lists_read"), offline=True,
       args=(Arg("имя", "str", optional=True),),
       examples=("chimera lists show", "chimera lists show youtube")),
    _a("lists", "save", handler="lists_save", methods=("lists_save",), level=APP, offline=True,
       args=(Arg("имя", "str"), Arg("file", "str", optional=True, flag=True)),
       examples=("chimera lists save youtube --file youtube.txt",)),
    _a("lists", "create", handler="lists_create",
       methods=("lists_create",), level=APP, offline=True, args=(Arg("имя", "str"),),
       examples=("chimera lists create games",)),
    _a("lists", "delete", handler="lists_delete",
       methods=("lists_delete",), level=APP, args=(Arg("имя", "str"),),
       examples=("chimera lists delete games",)),
    _a("lists", "rename",
       handler="lists_rename", methods=("lists_rename",), level=APP,
       args=(Arg("старое", "str"), Arg("новое", "str")), examples=("chimera lists rename games play",)),
    _a("lists", "add", handler="lists_add", methods=("lists_read", "lists_save", "lists_create"),
       level=APP, offline=True, args=(Arg("имя", "str"), Arg("домены", "names1")),
       examples=("chimera lists add youtube ytimg.com googlevideo.com",)),
    _a("lists", "remove", handler="lists_remove",
       methods=("lists_read", "lists_save"), level=APP, offline=True,
       args=(Arg("имя", "str"), Arg("домены", "names1")),
       examples=("chimera lists remove youtube ytimg.com",)),
    _a("lists", "validate", handler="lists_validate", methods=("lists_validate",), offline=True,
       args=(Arg("имя", "str", optional=True),),
       examples=("chimera lists validate", "chimera lists validate youtube --json")),
    _a("lists", "apply", handler="lists_apply", methods=("lists_apply",), level=APP,
       args=(Arg("имя", "str", optional=True),),
       examples=("chimera lists apply", "chimera lists apply youtube")),

    # --- проверки --------------------------------------------------------------------------
    _a("check", "site", handler="check_site", offline=True,
       methods=("block_check_one", "chebur_check_one"),
       args=(Arg("домен", "str"),
             Arg("only", "choice", optional=True, flag=True, choices=("local", "registry"))),
       examples=("chimera check discord.com", "chimera check site discord.com --only local")),
    _a("check", "list", handler="check_list", offline=True,
       methods=("block_check_one", "chebur_check_one"),
       args=(Arg("список", "str"),
             Arg("only", "choice", optional=True, flag=True, choices=("local", "registry"))),
       examples=("chimera check list discord",)),
    _a("check", "status", "chebur_status", examples=("chimera check status",)),

    # --- логи, служба, PATH ----------------------------------------------------------------------
    _a("logs", "", handler="logs", offline=True,
       methods=("winws_log", "proxy_log", "tg_log"),
       args=(Arg("модуль", "choice", choices=("winws", "proxy", "tg")),
             Arg("tail", "int", optional=True, flag=True)),
       examples=("chimera logs winws", "chimera logs proxy --tail 100")),
    _a("service", "", handler="service", level=SYSTEM, offline=True,
       args=(Arg("команда", "choice", choices=("install", "uninstall", "start", "stop", "status", "run")),
             Arg("параметры", "rest", optional=True)),
       examples=("chimera service status", "chimera service install --dry-run")),
    _a("docs", "", handler="docs", offline=True,
       args=(Arg("тема", "choice", optional=True, choices=("commands", "layout", "output")),),
       examples=("chimera docs", "chimera docs layout", "chimera docs --json")),
    _a("agent-info", "", handler="agent_info", offline=True, examples=("chimera agent-info --json",)),
    _a("path", "show",
       handler="path_show", offline=True, examples=("chimera path show",)),
    _a("path", "add", handler="path_add", level=APP, offline=True,
       examples=("chimera path add",)),
    _a("path", "remove",
       handler="path_remove", level=APP, offline=True, examples=("chimera path remove",)),
)

BY_GROUP: dict[str, dict[str, Action]] = {}
for _act in ACTIONS:
    BY_GROUP.setdefault(_act.group, {})[_act.name] = _act

# Для этих групп первое слово, не похожее на действие, считается параметром действия по умолчанию
# (`chimera check discord.com` = `chimera check site discord.com`).
DEFAULT_ACTION = {"check": "site"}


def allowed_methods() -> frozenset:
    """Методы Api, доступные по каналу управления: всё, что нужно командам таблицы."""
    return frozenset(m for a in ACTIONS for m in a.api_methods)
