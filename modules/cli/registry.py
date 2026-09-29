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
"""

from dataclasses import dataclass

READ, APP, SYSTEM = "read", "app", "system"
LEVEL_TITLES = {READ: "чтение", APP: "изменение приложения", SYSTEM: "изменение системы"}


@dataclass(frozen=True)
class Arg:
    name: str
    kind: str = "str"        # str | int | bool | names | names1 | value | choice | switch
    help: str = ""
    optional: bool = False
    choices: tuple = ()
    flag: bool = False       # --имя значение, а не позиционный параметр
    default: object = None   # что уйти в Api, если не указано


@dataclass(frozen=True)
class Action:
    group: str
    name: str                # "" — у группы одно действие (chimera status)
    summary: str
    ui: str = ""             # где это в интерфейсе (для таблицы паритета)
    method: str | None = None
    methods: tuple = ()      # если действие составное и зовёт несколько методов Api
    args: tuple = ()
    fixed: tuple = ()        # аргументы, которые команда подставляет сама (hosts on → True)
    level: str = READ
    examples: tuple = ()
    handler: str | None = None
    offline: bool = False    # работает и без запущенной Chimera

    @property
    def command(self) -> str:
        return f"{self.group} {self.name}".strip()

    @property
    def api_methods(self) -> tuple:
        return tuple(self.methods) + ((self.method,) if self.method else ())


GROUPS: dict[str, str] = {
    "status": "что работает сейчас",
    "start": "запустить Chimera без окна (в трее)",
    "stop": "закрыть Chimera",
    "restart": "перезапустить Chimera",
    "version": "версия программы и протокола",
    "update": "обновление Chimera",
    "autostart": "запуск Chimera вместе с Windows",
    "discord": "очистка кэша Discord",
    "sources": "внешние источники: zapret2, стратегии Flowseal и др.",
    "config": "настройки программы (config.json)",
    "winws": "обход DPI (zapret2 / winws2)",
    "proxy": "прокси на sing-box",
    "tg": "Telegram-прокси",
    "hosts": "подмена IP в системном hosts",
    "dns": "системный DNS и DNS-провайдеры",
    "panic": "выключить всё разом: обход, прокси, Telegram, hosts, DNS, службу",
    "doctor": "диагностика: почему обход может не работать",
    "lists": "списки доменов",
    "check": "открывается ли сайт и заблокирован ли он",
    "logs": "последние строки логов модулей",
    "service": "фоновая служба Windows",
    "path": "команда chimera в PATH пользователя",
    "docs": "документация этой версии: команды, папки и файлы, формат вывода",
    "agent-info": "сводка для агентов: версии, команды с уровнями, пути (`--json`)",
}

# Что не превращается в команду и почему. Тест паритета падает на любом публичном методе
# Api, которого нет ни в таблице действий, ни здесь.
EXCLUDED: dict[str, str] = {
    "dispatch": "внутренний вход моста окна, его роль у канала управления",
    "shutdown": "гашение модулей при выходе из окна; в терминале это `chimera stop`",
    "open_url": "открывает ссылку в браузере на компьютере пользователя; в терминале адрес и так виден",
    "tg_open_link": "открывает Telegram на этом компьютере; ссылку даёт `chimera tg link`",
    "hub_snapshot": "подписка окна на push-события состояния",
    "hub_watch": "подписка окна на push-события состояния",
    "hub_refresh": "подписка окна на push-события состояния",
    "block_check_start": "результаты приходят push-событиями окна; в CLI то же делает `chimera check list <список>`",
    "chebur_check_start": "результаты приходят push-событиями окна; в CLI то же делает `chimera check list <список>`",
}

ONOFF = Arg("значение", "bool", "on или off")


def _a(group, name, summary, ui, method=None, args=(), level=READ, examples=(), handler=None,
       offline=False, methods=(), fixed=()):
    return Action(group, name, summary, ui, method, tuple(methods), tuple(args), tuple(fixed), level,
                  tuple(examples), handler, offline)


ACTIONS: tuple[Action, ...] = (
    # --- приложение ---------------------------------------------------------------------
    _a("status", "", "Состояние приложения и модулей: обход, прокси, Telegram-прокси, hosts.",
       "Обзор: карточки модулей", handler="status", level=READ,
       methods=("app_info", "winws_state", "proxy_state", "tg_state", "hosts_state"),
       examples=("chimera status", "chimera status --json")),
    _a("version", "", "Версия программы и версия протокола командной строки.",
       "Настройки: версия программы", handler="version", offline=True,
       examples=("chimera --version", "chimera version --json")),
    _a("start", "", "Запустить Chimera без окна, в трее. Права администратора запросит сама программа.",
       "Запуск программы / автозапуск", handler="start", level=APP, examples=("chimera start",)),
    _a("stop", "", "Закрыть Chimera и погасить её модули.",
       "Меню значка → Выход", handler="stop", level=APP, examples=("chimera stop",)),
    _a("restart", "", "Перезапустить Chimera.",
       "Перезапуск программы", handler="restart", level=APP, examples=("chimera restart",)),
    _a("update", "state", "Состояние обновления: текущая и найденная версии, стадия.",
       "Настройки → Обновление Chimera: статус", "selfupdate_state", examples=("chimera update state",)),
    _a("update", "check", "Проверить, вышла ли новая версия.",
       "Настройки → Обновление Chimera → «Проверить»", "selfupdate_check", examples=("chimera update check",)),
    _a("update", "install", "Скачать, проверить и установить найденную версию; программа перезапустится.",
       "Настройки → Обновление Chimera → «Обновить»", "selfupdate_install", level=SYSTEM,
       examples=("chimera update check && chimera update install",)),
    _a("autostart", "state", "Включён ли запуск вместе с Windows.",
       "Настройки → Запускать вместе с Windows", "autostart_get", examples=("chimera autostart state",)),
    _a("autostart", "set", "Включить или выключить запуск вместе с Windows (нужны права администратора).",
       "Настройки → Запускать вместе с Windows", "autostart_set", (ONOFF,), SYSTEM,
       ("chimera autostart set on",)),
    _a("discord", "clear-cache", "Очистить кэш Discord (Discord должен быть закрыт).",
       "Настройки → Очистить кэш Discord", "discord_clear_cache", level=APP,
       examples=("chimera discord clear-cache",)),
    _a("sources", "versions", "Локальные версии внешних источников (без сети).",
       "Настройки → Источники и обновления", "upstream_versions", examples=("chimera sources versions",)),
    _a("sources", "check", "Сверить версии источников с GitHub (все или один).",
       "Настройки → Источники и обновления → «Проверить»", handler="sources_check",
       methods=("upstream_check_updates", "upstream_check_one"),
       args=(Arg("имя", "str", "источник; без имени — все", optional=True),),
       examples=("chimera sources check", "chimera sources check zapret2")),
    _a("sources", "update", "Подтянуть свежую версию источника (git fetch + checkout).",
       "Настройки → Источники и обновления → «Обновить»", "upstream_update",
       (Arg("имя", "str", "источник из `chimera sources versions`"),), SYSTEM,
       ("chimera sources update zapret2",)),
    _a("config", "get", "Показать настройки программы: все или одну.",
       "Настройки", handler="config_get", methods=("config_read",), offline=True,
       args=(Arg("ключ", "str", "имя настройки; без него — все", optional=True),),
       examples=("chimera config get", "chimera config get update_channel")),
    _a("config", "set", "Изменить настройку. Доступно то, что меняет окно: ui_backend, auto_elevate, "
       "close_to_tray, update_channel, update_check. Остальное — правкой config.json.",
       "Настройки: переключатели и выбор", handler="config_set", methods=("config_set",), level=APP,
       offline=True, args=(Arg("ключ", "str", "имя настройки"), Arg("значение", "value", "true/false, число или строка")),
       examples=("chimera config set update_channel beta", "chimera config set close_to_tray false")),

    # --- обход DPI ------------------------------------------------------------------
    _a("winws", "state", "Состояние обхода: запущен ли, стратегия, списки, ошибка, версия.",
       "Стратегии: шапка, Обзор", "winws_state", examples=("chimera winws state",)),
    _a("winws", "strategies", "Список доступных стратегий.",
       "Стратегии: список карточек", handler="winws_strategies", methods=("winws_state",),
       examples=("chimera winws strategies --json",)),
    _a("winws", "start", "Запустить стратегию. Без имени — последнюю использованную.",
       "Стратегии → «Запустить» / Обзор → включатель", handler="winws_start",
       methods=("winws_state", "winws_start"),
       args=(Arg("стратегия", "str", "id из `chimera winws strategies`; по умолчанию последняя", optional=True),),
       level=SYSTEM, examples=("chimera winws start", "chimera winws start alt2")),
    _a("winws", "stop", "Остановить обход.", "Стратегии / Обзор → «Остановить»", "winws_stop", level=SYSTEM,
       examples=("chimera winws stop",)),
    _a("winws", "autostart", "Запускать стратегию при старте Chimera.",
       "Стратегии → автозапуск", "winws_set_autostart", (ONOFF,), APP, ("chimera winws autostart on",)),
    _a("winws", "lists", "Какие списки доменов гнать через обход (без имён — очистить). Применяется сразу.",
       "Стратегии → выбор списков", "winws_set_lists",
       (Arg("списки", "names", "имена списков", optional=True),), APP,
       ("chimera winws lists youtube discord",)),
    _a("winws", "filters", "Состояние фильтров: game, ipset, fake-блобы.",
       "Стратегии → фильтры", "filters_state", examples=("chimera winws filters",)),
    _a("winws", "game", "Игровой фильтр: off, all, tcp или udp; порты — необязательно.",
       "Стратегии → Game-фильтр", "game_filter_set",
       (Arg("режим", "choice", "режим", choices=("off", "all", "tcp", "udp")),
        Arg("tcp", "str", "диапазон TCP-портов", optional=True, flag=True),
        Arg("udp", "str", "диапазон UDP-портов", optional=True, flag=True)), SYSTEM,
       ("chimera winws game udp", "chimera winws game all --tcp 1024-65535")),
    _a("winws", "ipset", "Режим ipset: none, any или loaded.",
       "Стратегии → IPSet", "ipset_set",
       (Arg("режим", "choice", "режим", choices=("none", "any", "loaded")),), APP,
       ("chimera winws ipset loaded",)),
    _a("winws", "ipset-update", "Скачать свежий список подсетей (ipset).",
       "Стратегии → IPSet → «Обновить»", "ipset_update", level=SYSTEM, examples=("chimera winws ipset-update",)),
    _a("winws", "fake", "Подставить fake-блоб в слот (discord или game).",
       "Стратегии → Fake", "fake_set",
       (Arg("слот", "str", "слот из `chimera winws filters`"), Arg("блоб", "str", "имя блоба")), APP,
       ("chimera winws fake discord quic_initial_www_google_com",)),

    # --- прокси ---------------------------------------------------------------------
    _a("proxy", "state", "Состояние прокси: запущен ли, режим, списки, число доменов, ядро.",
       "Прокси: шапка, Обзор", "proxy_state", examples=("chimera proxy state",)),
    _a("proxy", "start", "Запустить прокси (sing-box).", "Прокси / Обзор → включатель", "proxy_start",
       level=SYSTEM, examples=("chimera proxy start",)),
    _a("proxy", "stop", "Остановить прокси.", "Прокси / Обзор → «Остановить»", "proxy_stop", level=SYSTEM,
       examples=("chimera proxy stop",)),
    _a("proxy", "mode", "Режим прокси: pac (без админа), split (выборочный TUN) или tun (весь трафик).",
       "Прокси → режим", "proxy_set_mode",
       (Arg("режим", "choice", "режим", choices=("pac", "split", "tun")),), SYSTEM,
       ("chimera proxy mode pac",)),
    _a("proxy", "link", "Задать ссылку прокси (vless://, trojan://, ss://, vmess://). "
       "`-` — прочитать из stdin, `--clear` — удалить.", "Прокси → поле ссылки", handler="proxy_link",
       methods=("proxy_set_link",), level=APP,
       args=(Arg("ссылка", "str", "ссылка или `-`", optional=True), Arg("clear", "switch", "удалить ссылку", flag=True)),
       examples=("chimera proxy link vless://...", "echo vless://... | chimera proxy link -", "chimera proxy link --clear")),
    _a("proxy", "lists", "Какие списки идут через прокси (без имён — очистить). Применяется сразу.",
       "Прокси → выбор списков", "proxy_set_lists", (Arg("списки", "names", "имена списков", optional=True),), APP,
       ("chimera proxy lists youtube telegram",)),
    _a("proxy", "apps", "Приложения для выборочного TUN, имена образов (Discord.exe). Без имён — очистить.",
       "Прокси → приложения", "proxy_set_apps", (Arg("приложения", "names", "Discord.exe …", optional=True),), APP,
       ("chimera proxy apps Discord.exe chrome.exe",)),
    _a("proxy", "apps-running", "Запущенные сейчас программы пользователя (для выбора в выборочный TUN).",
       "Прокси → «Запущенные программы»", "proxy_apps_snapshot", examples=("chimera proxy apps-running",)),
    _a("proxy", "autostart", "Запускать прокси при старте Chimera.",
       "Прокси → автозапуск", "proxy_set_autostart", (ONOFF,), APP, ("chimera proxy autostart on",)),
    _a("proxy", "core-download", "Скачать ядро sing-box (пиннутая версия, с проверкой SHA256).",
       "Прокси → «Скачать sing-box»", "proxy_download_core", level=APP, examples=("chimera proxy core-download",)),

    # --- Telegram-прокси --------------------------------------------------------------
    _a("tg", "state", "Состояние Telegram-прокси и его настройки.",
       "Telegram: шапка, Обзор", "tg_state", examples=("chimera tg state",)),
    _a("tg", "start", "Запустить Telegram-прокси.", "Telegram / Обзор → включатель", "tg_start", level=APP,
       examples=("chimera tg start",)),
    _a("tg", "stop", "Остановить Telegram-прокси.", "Telegram / Обзор → «Остановить»", "tg_stop", level=APP,
       examples=("chimera tg stop",)),
    _a("tg", "stats", "Счётчики работающего Telegram-прокси.", "Telegram → статистика", "tg_stats",
       examples=("chimera tg stats",)),
    _a("tg", "link", "Ссылка tg://proxy для подключения (секрет скрыт без --show-secrets).",
       "Telegram → «Скопировать ссылку»", handler="tg_link", methods=("tg_state",),
       examples=("chimera tg link --show-secrets",)),
    _a("tg", "config", "Изменить адрес, порт, секрет или автозапуск (остальное не меняется).",
       "Telegram → настройки", handler="tg_config", methods=("tg_state", "tg_set_config"), level=APP,
       args=(Arg("host", "str", "адрес; 0.0.0.0 — открыть для устройств в сети", optional=True, flag=True),
             Arg("port", "int", "порт", optional=True, flag=True),
             Arg("secret", "str", "секрет из 32 hex-символов", optional=True, flag=True),
             Arg("autostart", "bool", "on или off", optional=True, flag=True)),
       examples=("chimera tg config --port 1443", "chimera tg config --host 0.0.0.0")),
    _a("tg", "regen-secret", "Сгенерировать новый секрет (старая ссылка перестанет работать).",
       "Telegram → «Новый секрет»", "tg_regen_secret", level=APP, examples=("chimera tg regen-secret",)),
    _a("tg", "advanced", "Продвинутые настройки ядра: ключ=значение (значение — JSON или строка).",
       "Telegram → продвинутые", handler="tg_advanced", methods=("tg_set_advanced",), level=APP,
       args=(Arg("настройки", "names1", "ключ=значение …"),),
       examples=("chimera tg advanced fake_tls_domain=example.com", "chimera tg advanced fallback_cfproxy=false")),
    _a("tg", "check-update", "Проверить обновление ядра Telegram-прокси.",
       "Telegram → «Проверить обновление»", "tg_check_update", examples=("chimera tg check-update",)),

    # --- hosts ------------------------------------------------------------------------
    _a("hosts", "state", "Состояние подмены hosts: применена ли, сколько записей.",
       "Hosts: шапка, Обзор", "hosts_state", examples=("chimera hosts state",)),
    _a("hosts", "overview", "Всё по hosts: провайдеры, списки, привязки, состояние.",
       "Hosts: вся вкладка", "hosts_overview", examples=("chimera hosts overview --json",)),
    _a("hosts", "on", "Включить подмену hosts (привязки сохраняются).",
       "Hosts / Обзор → включатель", "hosts_set_enabled", level=SYSTEM, fixed=(True,),
       examples=("chimera hosts on",)),
    _a("hosts", "off", "Выключить подмену hosts: блок из файла убирается, привязки остаются.",
       "Hosts / Обзор → включатель", "hosts_set_enabled", level=SYSTEM, fixed=(False,),
       examples=("chimera hosts off",)),
    _a("hosts", "assign", "Привязать списки к провайдерам: провайдер=список,список (пусто — снять). "
       "Меняются только указанные провайдеры; --replace заменяет все привязки.",
       "Hosts → привязка списков", handler="hosts_assign", methods=("hosts_state", "hosts_set_assignments"),
       level=SYSTEM, args=(Arg("привязки", "names", "провайдер=список,список …", optional=True),
                           Arg("replace", "switch", "заменить все привязки", flag=True)),
       examples=("chimera hosts assign comss=youtube,discord", "chimera hosts assign xbox=")),
    _a("hosts", "provider-add", "Добавить hosts-провайдера (имя, DoH-адрес, серверы).",
       "Hosts → «Добавить провайдера»", "hosts_add_provider",
       (Arg("имя", "str"), Arg("doh", "str", "адрес DoH или - "), Arg("серверы", "names1", "IP-адреса")), APP,
       ("chimera hosts provider-add my https://dns.example/dns-query 1.2.3.4",)),
    _a("hosts", "provider-delete", "Удалить hosts-провайдера.", "Hosts → провайдер → «Удалить»",
       "hosts_delete_provider", (Arg("id", "str", "id провайдера"),), APP, ("chimera hosts provider-delete my",)),
    _a("hosts", "ping", "Проверить доступность hosts-провайдера.", "Hosts → провайдер → «Пинг»",
       "hosts_ping_one", (Arg("id", "str", "id провайдера"),), examples=("chimera hosts ping comss",)),
    _a("hosts", "background", "Настройки фонового потока hosts: ключ=значение (значение — JSON).",
       "Hosts → фоновые опции", handler="hosts_background", methods=("hosts_set_background", "hosts_overview"),
       level=APP, args=(Arg("настройки", "names", "ключ=значение …", optional=True),),
       examples=("chimera hosts background", "chimera hosts background auto_update=true")),

    # --- DNS --------------------------------------------------------------------------
    _a("dns", "state", "Адаптеры, их текущий DNS и провайдеры.", "DNS: вся вкладка", "dns_state",
       examples=("chimera dns state",)),
    _a("dns", "ping", "Пинг DNS-провайдеров: всех или одного.", "DNS → «Проверить скорость»",
       handler="dns_ping", methods=("dns_ping", "dns_ping_one"),
       args=(Arg("id", "str", "провайдер; без него — все", optional=True),), examples=("chimera dns ping",)),
    _a("dns", "probe", "Проверить, отвечает ли провайдер на «обходные» и рекламные домены.",
       "DNS → «Проба» у провайдера", "dns_probe", (Arg("id", "str", "id провайдера"),),
       examples=("chimera dns probe cloudflare",)),
    _a("dns", "probe-config", "Домены пробы: показать, либо задать --bypass и --ad.",
       "DNS → настройка пробы", handler="dns_probe_config", methods=("dns_probe_config", "dns_set_probe_config"),
       level=APP, args=(Arg("bypass", "str", "домен «обходной» пробы", optional=True, flag=True),
                        Arg("ad", "str", "домен рекламной пробы", optional=True, flag=True)),
       examples=("chimera dns probe-config", "chimera dns probe-config --bypass rutracker.org")),
    _a("dns", "set", "Поставить DNS-провайдера на адаптер (нужны права администратора).",
       "DNS → провайдер → «Применить»", "dns_set",
       (Arg("адаптер", "int", "номер адаптера из `chimera dns state`"), Arg("провайдер", "str", "id провайдера")),
       SYSTEM, ("chimera dns set 12 cloudflare",)),
    _a("dns", "reset", "Вернуть DNS адаптера на автоматический (DHCP).", "DNS → «Сбросить»", "dns_reset",
       (Arg("адаптер", "int", "номер адаптера из `chimera dns state`"),), SYSTEM, ("chimera dns reset 12",)),
    _a("dns", "provider-add", "Добавить DNS-провайдера.", "DNS → «Добавить провайдера»", "dns_add_provider",
       (Arg("имя", "str"), Arg("серверы", "names1", "IPv4-адреса"),
        Arg("ipv6", "str", "IPv6-адреса через запятую", optional=True, flag=True, default=""),
        Arg("doh", "str", "адрес DoH", optional=True, flag=True, default=""),
        Arg("dot", "str", "имя DoT", optional=True, flag=True, default=""),
        Arg("unblock", "switch", "разблокирующий", flag=True, default=False),
        Arg("filtering", "switch", "с фильтрацией", flag=True, default=False)), APP,
       ("chimera dns provider-add my 9.9.9.9 149.112.112.112 --doh https://dns.quad9.net/dns-query",)),
    _a("dns", "provider-delete", "Удалить DNS-провайдера.", "DNS → провайдер → «Удалить»", "dns_delete_provider",
       (Arg("id", "str", "id провайдера"),), APP, ("chimera dns provider-delete my",)),

    _a("dns", "trial", "Поставить DNS с автооткатом: не подтвердите за --seconds секунд — вернётся прежний.",
       "DNS → провайдер → «Применить» (плашка «Оставить / Вернуть»)", "dns_set_trial",
       (Arg("адаптер", "int", "номер адаптера из `chimera dns state`"), Arg("провайдер", "str", "id провайдера"),
        Arg("seconds", "int", "секунд на подтверждение (5–120)", optional=True, flag=True, default=15)), SYSTEM,
       ("chimera dns trial 12 cloudflare", "chimera dns trial 12 cloudflare --seconds 30")),
    _a("dns", "trial-confirm", "Оставить новый DNS после `dns trial`; без адаптера — все ожидающие.",
       "DNS → плашка → «Оставить»", "dns_trial_confirm",
       (Arg("адаптер", "int", "номер адаптера; без него — все", optional=True),), APP,
       ("chimera dns trial-confirm 12",)),
    _a("dns", "trial-revert", "Вернуть прежний DNS сразу, не дожидаясь таймера.",
       "DNS → плашка → «Вернуть сейчас»", "dns_trial_revert",
       (Arg("адаптер", "int", "номер адаптера; без него — все", optional=True),), SYSTEM,
       ("chimera dns trial-revert 12",)),
    _a("dns", "record-start", "Начать запись доменов сайта: запоминает имена в кэше DNS Windows (кэш сбрасывается, "
       "если есть права администратора).", "Списки → «Записать домены сайта» → «Начать»", "dns_record_start",
       level=APP, examples=("chimera dns record-start",)),
    _a("dns", "record-stop", "Закончить запись: домены, появившиеся с начала, по основным доменам; "
       "трекеры помечены. Откройте нужный сайт между start и stop.",
       "Списки → «Записать домены сайта» → «Стоп»", "dns_record_stop", level=APP,
       examples=("chimera dns record-start", "chimera dns record-stop --json")),

    _a("panic", "", "Выключить всё разом: обход, прокси, Telegram-прокси, службу, подмену hosts; вернуть DNS на "
       "адаптерах, где его ставила Chimera. Шаги независимы, сбой одного не мешает остальным. Только по просьбе пользователя.",
       "Обзор → «Выключить всё», меню значка в трее", "panic_all", level=SYSTEM, examples=("chimera panic",)),

    _a("doctor", "", "Диагностика: права, драйвер WinDivert, порты, чужие процессы, прокси в системе. "
       "--report даёт Markdown для issue (ссылки прокси и секреты скрыты). Ничего не меняет.",
       "Настройки → Диагностика", handler="doctor", methods=("doctor_run", "doctor_report"),
       args=(Arg("report", "switch", "отчёт в Markdown", flag=True, default=False),),
       examples=("chimera doctor", "chimera doctor --report", "chimera doctor --json")),

    _a("config", "export", "Собрать конфиг для отправки: разделы --sections (по умолчанию переносимые: "
       "lists,proxy,hosts,dns,telegram; winws зависит от провайдера и включается явно). Ссылка прокси и секреты "
       "не входят. --file — записать в файл.", "Настройки → Обмен конфигом → «Поделиться»", handler="config_export",
       methods=("config_export",),
       args=(Arg("sections", "str", "разделы через запятую", optional=True, flag=True),
             Arg("file", "str", "записать в файл", optional=True, flag=True)),
       examples=("chimera config export --file my.chimera", "chimera config export --sections proxy,lists")),
    _a("config", "import-preview", "Показать, что изменит чужой конфиг (файл или `-` для stdin): применится, "
       "пропущено, требует подтверждения. Ничего не меняет.", "Настройки → Обмен конфигом → «Применить…» → «Проверить»",
       handler="config_import_preview", methods=("config_import_preview",),
       args=(Arg("файл", "str", "файл конфига или - для stdin"),),
       examples=("chimera config import-preview friend.chimera",)),
    _a("config", "import", "Применить чужой конфиг (разделы --sections, по умолчанию все, кроме зависящих от "
       "провайдера). Сначала смотрите `config import-preview`. Чужие серверы DNS/hosts и домены Telegram — только с "
       "--confirm. Перед применением файлы копируются в data/backups.", "Настройки → Обмен конфигом → «Применить»",
       handler="config_import", methods=("config_import_apply", "config_import_preview"),
       args=(Arg("файл", "str", "файл конфига или - для stdin"),
             Arg("sections", "str", "разделы через запятую", optional=True, flag=True),
             Arg("confirm", "switch", "разрешить чужие серверы DNS/hosts и домены Telegram", flag=True, default=False)),
       level=APP, examples=("chimera config import friend.chimera --sections proxy,lists",)),

    # --- списки ----------------------------------------------------------------------
    _a("lists", "show", "Списки с числом доменов и подключениями; с именем — содержимое списка.",
       "Списки: список и редактор", handler="lists_show", methods=("lists_all", "lists_read"), offline=True,
       args=(Arg("имя", "str", "список; без него — все", optional=True),),
       examples=("chimera lists show", "chimera lists show youtube")),
    _a("lists", "save", "Записать список целиком из файла (--file) или stdin.",
       "Списки → редактор → «Сохранить»", handler="lists_save", methods=("lists_save",), level=APP, offline=True,
       args=(Arg("имя", "str", "список"), Arg("file", "str", "файл со списком; без него — stdin", optional=True, flag=True)),
       examples=("chimera lists save youtube --file youtube.txt",)),
    _a("lists", "create", "Создать пустой список.", "Списки → «Новый список»", handler="lists_create",
       methods=("lists_create",), level=APP, offline=True, args=(Arg("имя", "str", "латиница, цифры, . - _"),),
       examples=("chimera lists create games",)),
    _a("lists", "delete", "Удалить список.", "Списки → «Удалить»", handler="lists_delete",
       methods=("lists_delete",), level=APP, args=(Arg("имя", "str"),),
       examples=("chimera lists delete games",)),
    _a("lists", "rename", "Переименовать список вместе со ссылками на него.", "Списки → «Переименовать»",
       handler="lists_rename", methods=("lists_rename",), level=APP,
       args=(Arg("старое", "str"), Arg("новое", "str")), examples=("chimera lists rename games play",)),
    _a("lists", "add", "Добавить домены в список (список создаётся, если его нет). Применяется сразу.",
       "Списки → редактор", handler="lists_add", methods=("lists_read", "lists_save", "lists_create"),
       level=APP, offline=True, args=(Arg("имя", "str"), Arg("домены", "names1", "домены или подсети")),
       examples=("chimera lists add youtube ytimg.com googlevideo.com",)),
    _a("lists", "remove", "Убрать домены из списка.", "Списки → редактор", handler="lists_remove",
       methods=("lists_read", "lists_save"), level=APP, offline=True,
       args=(Arg("имя", "str"), Arg("домены", "names1", "домены или подсети")),
       examples=("chimera lists remove youtube ytimg.com",)),
    _a("lists", "validate", "Проверить файл списка, ничего не меняя: кодировка, синтаксис доменов и подсетей, "
       "дубликаты. Без имени — все списки. Есть ошибки — код возврата 1.",
       "Только командная строка: проверка файла до применения", handler="lists_validate", offline=True,
       args=(Arg("имя", "str", "список; без него — все", optional=True),),
       examples=("chimera lists validate", "chimera lists validate youtube --json")),
    _a("lists", "apply", "Применить список к обходу, прокси и hosts сейчас (без имени — все). Обычно не нужно: "
       "правку lists/*.txt на диске работающая программа подхватывает сама, а сохранение через `lists save` "
       "применяется сразу. Нужна работающая Chimera с окном или в трее.",
       "Списки → «Сохранить» (применение)", handler="lists_apply", methods=("lists_apply",), level=APP,
       args=(Arg("имя", "str", "список; без него — все", optional=True),),
       examples=("chimera lists apply", "chimera lists apply youtube")),

    # --- проверки --------------------------------------------------------------------------
    _a("check", "site", "Проверить один домен: доступность с этого компьютера и наличие в реестре блокировок.",
       "Проверки → поле «Проверить сайт»", handler="check_site", offline=True,
       methods=("block_check_one", "chebur_check_one"),
       args=(Arg("домен", "str", "домен или адрес"),
             Arg("only", "choice", "только local или registry", optional=True, flag=True, choices=("local", "registry"))),
       examples=("chimera check discord.com", "chimera check site discord.com --only local")),
    _a("check", "list", "Проверить все домены списка (параллельно), как «Проверить список» в окне.",
       "Проверки → «Проверить список»", handler="check_list", offline=True,
       methods=("block_check_one", "chebur_check_one"),
       args=(Arg("список", "str", "имя списка"),
             Arg("only", "choice", "только local или registry", optional=True, flag=True, choices=("local", "registry"))),
       examples=("chimera check list discord",)),
    _a("check", "status", "Состояние сервиса реестра блокировок (версия, дата обновления).",
       "Проверки → шапка", "chebur_status", examples=("chimera check status",)),

    # --- логи, служба, PATH ----------------------------------------------------------------------
    _a("logs", "", "Последние строки лога модуля: winws, proxy или tg.",
       "Стратегии / Прокси / Telegram → лог", handler="logs", offline=True,
       methods=("winws_log", "proxy_log", "tg_log"),
       args=(Arg("модуль", "choice", "модуль", choices=("winws", "proxy", "tg")),
             Arg("tail", "int", "сколько последних строк (по умолчанию 40)", optional=True, flag=True)),
       examples=("chimera logs winws", "chimera logs proxy --tail 100")),
    _a("service", "", "Фоновая служба: install, uninstall, start, stop, status, run (как `main.py service`).",
       "Настройки → фоновая служба (командная строка)", handler="service", level=SYSTEM, offline=True,
       args=(Arg("команда", "choice", "действие", choices=("install", "uninstall", "start", "stop", "status", "run")),
             Arg("параметры", "rest", "например --dry-run", optional=True)),
       examples=("chimera service status", "chimera service install --dry-run")),
    _a("docs", "", "Документация этой версии программы. Темы: commands (команды), layout (папки и файлы), "
       "output (коды возврата и формат --json). Без темы — оглавление; с --json — всё в машинном виде.",
       "Справка", handler="docs", offline=True,
       args=(Arg("тема", "choice", "тема", optional=True, choices=("commands", "layout", "output")),),
       examples=("chimera docs", "chimera docs layout", "chimera docs --json")),
    _a("agent-info", "", "Сводка для агентов: версия программы и протокола, совместимая версия скилла, "
       "команды с уровнями, пути к данным. Для машинного разбора — с --json.",
       "Справка", handler="agent_info", offline=True, examples=("chimera agent-info --json",)),
    _a("path", "show", "Есть ли папка программы в PATH пользователя.", "Настройки → командная строка",
       handler="path_show", offline=True, examples=("chimera path show",)),
    _a("path", "add", "Добавить папку программы в PATH пользователя (после этого `chimera` работает из любой папки).",
       "Настройки → командная строка", handler="path_add", level=APP, offline=True,
       examples=("chimera path add",)),
    _a("path", "remove", "Убрать папку программы из PATH пользователя.", "Настройки → командная строка",
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
