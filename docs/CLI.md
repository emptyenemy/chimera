# Командная строка chimera

<!-- Файл сгенерирован: python tools/gen_cli_docs.py. Руками не править — правьте modules/cli/registry.py. -->

Всё, что делается в интерфейсе Chimera, делается командой `chimera …`. Справка встроена: `chimera --help`, `chimera <команда> --help`, `chimera docs`.

Запуск без аргументов из терминала печатает справку; двойной клик по `Chimera.exe` открывает окно. `chimera --window` и `chimera --browser` открывают окно или вкладку браузера.

## Общие параметры

- `--json` — машинный вывод
- `--show-secrets` — не скрывать секреты
- `--lang` — язык вывода: ru или en (по умолчанию из настроек)
- `-h/--help` — справка
- `--version` — версия

## Коды возврата

- `0` — успех
- `1` — ошибка выполнения (отказ приложения, нет такого объекта, сбой сети)
- `2` — неверные аргументы
- `3` — Chimera не запущена, старая версия приложения или нет связи

## Формат `--json`

Вывод — один объект:

- `schema` — версия формата вывода (сейчас 1); растёт только при несовместимых изменениях
- `ok` — true/false — успех команды
- `command` — команда без параметров, например `winws start`
- `level` — read | app | system — что команда меняет (только при ok=true)
- `data` — то, что вернул метод приложения, без потерь; у составных команд (status, check) — сводка
- `error` — при ok=false: {code, message, key, params}; code — usage, not_running, app_too_old, remote_error, forbidden, …; key и params — ключ сообщения в каталоге и его параметры (есть не у всех ошибок); message зависит от языка, code и key нет

## Уровни команд

- `read` — чтение
- `app` — изменение приложения
- `system` — изменение системы

Уровни нужны, чтобы ограничивать удалённые каналы. Ссылка прокси в выводе скрыта; `--show-secrets` показывает её. Ссылка и секрет Telegram-прокси видны всегда: это ключ к своему локальному прокси.

## Что в интерфейсе — какая команда

| В интерфейсе | Команда | Уровень |
|---|---|---|
| Терминал: Ctrl+E / Обзор → Разобрать маршрут | `chimera explain <домен> [--app <app>]` | read |
| Обзор: карточки модулей | `chimera status` | read |
| Настройки: версия программы | `chimera version` | read |
| Запуск программы / автозапуск | `chimera start` | app |
| Терминал: полноэкранный интерфейс | `chimera tui [--simple]` | app |
| Меню значка → Выход | `chimera stop` | app |
| Перезапуск программы | `chimera restart` | app |
| Настройки → Обновление Chimera: статус | `chimera update state` | read |
| Настройки → Обновление Chimera → «Проверить» | `chimera update check` | read |
| Настройки → Обновление Chimera → «Обновить» | `chimera update install` | system |
| Настройки → Запускать вместе с Windows | `chimera autostart state` | read |
| Настройки → Запускать вместе с Windows | `chimera autostart set <on|off>` | system |
| Настройки → Очистить кэш Discord | `chimera discord clear-cache` | app |
| Настройки → Источники и обновления | `chimera sources versions` | read |
| Настройки → Источники и обновления → «Проверить» | `chimera sources check [имя]` | read |
| Настройки → Источники и обновления → «Обновить» | `chimera sources update <имя>` | system |
| Настройки | `chimera config get [ключ]` | read |
| Настройки: переключатели и выбор | `chimera config set <ключ> <значение>` | app |
| Настройки → Язык | `chimera lang show` | read |
| Настройки → Язык | `chimera lang set <auto|ru|en>` | app |
| Окно: загрузка текстов интерфейса | `chimera lang catalog [ru|en]` | read |
| Плашка пробы на всех страницах | `chimera trial state` | read |
| Стратегии / Hosts / Прокси: Попробовать | `chimera trial start <strategy|hosts|tun> <target> [--seconds <seconds>] [--domains <domains>]` | system |
| Проба: Оставить | `chimera trial confirm <id>` | app |
| Проба: Вернуть | `chimera trial revert <id>` | system |
| Стратегии: шапка, Обзор | `chimera winws state` | read |
| Стратегии: список карточек | `chimera winws strategies` | read |
| Стратегии → «Запустить» / Обзор → включатель | `chimera winws start [стратегия]` | system |
| Стратегии / Обзор → «Остановить» | `chimera winws stop` | system |
| Стратегии → автозапуск | `chimera winws autostart <on|off>` | app |
| Стратегии → выбор списков | `chimera winws lists [списки…]` | app |
| Стратегии → фильтры | `chimera winws filters` | read |
| Стратегии → Game-фильтр | `chimera winws game <off|all|tcp|udp> [--tcp <tcp>] [--udp <udp>]` | system |
| Стратегии → IPSet | `chimera winws ipset <none|any|loaded>` | app |
| Стратегии → IPSet → «Обновить» | `chimera winws ipset-update` | system |
| Стратегии → Fake | `chimera winws fake <слот> <блоб>` | app |
| Прокси: шапка, Обзор | `chimera proxy state` | read |
| Прокси / Обзор → включатель | `chimera proxy start` | system |
| Прокси / Обзор → «Остановить» | `chimera proxy stop` | system |
| Прокси → режим | `chimera proxy mode <pac|split|tun>` | system |
| Прокси → поле ссылки | `chimera proxy link [ссылка] [--clear]` | app |
| Прокси → выбор списков | `chimera proxy lists [списки…]` | app |
| Прокси → приложения | `chimera proxy apps [приложения…]` | app |
| Прокси → «Запущенные программы» | `chimera proxy apps-running` | read |
| Прокси → автозапуск | `chimera proxy autostart <on|off>` | app |
| Прокси → «Скачать sing-box» | `chimera proxy core-download` | app |
| Telegram: шапка, Обзор | `chimera tg state` | read |
| Telegram / Обзор → включатель | `chimera tg start` | app |
| Telegram / Обзор → «Остановить» | `chimera tg stop` | app |
| Telegram → статистика | `chimera tg stats` | read |
| Telegram → «Скопировать ссылку» | `chimera tg link` | read |
| Telegram → настройки | `chimera tg config [--host <host>] [--port <port>] [--secret <secret>] [--autostart <autostart>]` | app |
| Telegram → «Новый секрет» | `chimera tg regen-secret` | app |
| Telegram → продвинутые | `chimera tg advanced <настройки…>` | app |
| Telegram → «Проверить обновление» | `chimera tg check-update` | read |
| Hosts: шапка, Обзор | `chimera hosts state` | read |
| Hosts: вся вкладка | `chimera hosts overview` | read |
| Hosts / Обзор → включатель | `chimera hosts on` | system |
| Hosts / Обзор → включатель | `chimera hosts off` | system |
| Hosts → привязка списков | `chimera hosts assign [привязки…] [--replace]` | system |
| Hosts → «Добавить провайдера» | `chimera hosts provider-add <имя> <doh> <серверы…>` | app |
| Hosts → провайдер → «Удалить» | `chimera hosts provider-delete <id>` | app |
| DNS: вся вкладка | `chimera dns state` | read |
| DNS → «Проверить скорость» | `chimera dns ping [id]` | read |
| DNS → «Проба» у провайдера | `chimera dns probe <id>` | read |
| DNS → настройка пробы | `chimera dns probe-config [--bypass <bypass>] [--ad <ad>]` | app |
| DNS → провайдер → «Применить» | `chimera dns set <адаптер> <провайдер>` | system |
| DNS → «Сбросить» | `chimera dns reset <адаптер>` | system |
| DNS → «Добавить провайдера» | `chimera dns provider-add <имя> <серверы…> [--ipv6 <ipv6>] [--doh <doh>] [--dot <dot>] [--unblock] [--filtering]` | app |
| DNS → провайдер → «Удалить» | `chimera dns provider-delete <id>` | app |
| Провайдеры | `chimera providers list` | read |
| Провайдеры → «Добавить» | `chimera providers add <имя> [серверы…] [--ipv6 <ipv6>] [--doh <doh>] [--dot <dot>] [--unblock] [--filtering]` | app |
| Провайдеры → провайдер → «Изменить» | `chimera providers edit <id> <имя> [серверы…] [--ipv6 <ipv6>] [--doh <doh>] [--dot <dot>] [--unblock] [--filtering]` | app |
| Провайдеры → провайдер → «Удалить» | `chimera providers delete <id>` | app |
| Провайдеры → встроенный провайдер → «Скрыть», «Скрытые» | `chimera providers hide <id> [on|off]` | app |
| DNS → провайдер → «Применить» (плашка «Оставить / Вернуть») | `chimera dns trial <адаптер> <провайдер> [--seconds <seconds>]` | system |
| DNS → плашка → «Оставить» | `chimera dns trial-confirm [адаптер]` | app |
| DNS → плашка → «Вернуть сейчас» | `chimera dns trial-revert [адаптер]` | system |
| Списки → «Записать домены сайта» → «Начать» | `chimera dns record-start` | app |
| Списки → «Записать домены сайта» → «Стоп» | `chimera dns record-stop` | app |
| Обзор → «Выключить всё», меню значка в трее | `chimera panic` | system |
| Настройки → Диагностика | `chimera doctor [--report]` | read |
| Настройки → Обмен конфигом → «Поделиться» | `chimera config export [--sections <sections>] [--file <file>]` | read |
| Настройки → Обмен конфигом → «Применить…» → «Проверить» | `chimera config import-preview <файл>` | read |
| Настройки → Обмен конфигом → «Применить» | `chimera config import <файл> [--sections <sections>] [--confirm]` | app |
| Настройки → Общее → Оформление. | `chimera config appearance` | read |
| Настройки → Общее → Оформление. | `chimera config appearance-preview <settings>` | read |
| Настройки → Общее → Оформление. | `chimera config appearance-apply <settings>` | app |
| Настройки → Общее → Оформление. | `chimera config appearance-refresh` | app |
| Настройки → Инструменты → Бэкапы настроек → Создать снимок | `chimera config backup` | app |
| Настройки → Инструменты → Бэкапы → Проверить и сохранить | `chimera config verify <домены…>` | app |
| Настройки → Инструменты → Последняя проверенная конфигурация | `chimera config verified` | read |
| Настройки → Инструменты → Резервные копии | `chimera config backups` | read |
| Настройки → Инструменты → Бэкапы → Сравнить. | `chimera config compare <first> <second>` | read |
| Настройки → Инструменты → Резервные копии → Предпросмотр | `chimera config restore-preview <id>` | read |
| Настройки → Инструменты → Резервные копии → Восстановить | `chimera config restore <id> [--confirm]` | system |
| Списки: список и редактор | `chimera lists show [имя]` | read |
| Списки → редактор → «Сохранить» | `chimera lists save <имя> [--file <file>]` | app |
| Списки → «Новый список» | `chimera lists create <имя>` | app |
| Списки → «Удалить» | `chimera lists delete <имя>` | app |
| Списки → «Переименовать» | `chimera lists rename <старое> <новое>` | app |
| Списки → редактор | `chimera lists add <имя> <домены…>` | app |
| Списки → редактор | `chimera lists remove <имя> <домены…>` | app |
| Только командная строка: проверка файла до применения | `chimera lists validate [имя]` | read |
| Списки → «Сохранить» (применение) | `chimera lists apply [имя]` | app |
| Проверки → поле «Проверить сайт» | `chimera check site <домен> [--only <only>]` | read |
| Проверки → «Проверить список» | `chimera check list <список> [--only <only>]` | read |
| Проверки → шапка | `chimera check status` | read |
| Стратегии / Прокси / Telegram → лог | `chimera logs <winws|proxy|tg> [--tail <tail>]` | read |
| Настройки → фоновая служба (командная строка) | `chimera service <install|uninstall|start|stop|status|run> [параметры…]` | system |
| Справка | `chimera docs [commands|layout|output]` | read |
| Справка | `chimera agent-info` | read |
| Настройки → командная строка | `chimera path show` | read |
| Настройки → командная строка | `chimera path add` | app |
| Настройки → командная строка | `chimera path remove` | app |

Не превращены в команды (с причинами):

- `dispatch` — внутренний вход моста окна, его роль у канала управления
- `shutdown` — гашение модулей при выходе из окна; в терминале это `chimera stop`
- `app_elevate` — Запрос UAC относится к локальному окну; команды выполняются из терминала с нужными правами.
- `open_url` — открывает ссылку в браузере на компьютере пользователя; в терминале адрес и так виден
- `tg_open_link` — открывает Telegram на этом компьютере; ссылку даёт `chimera tg link`
- `hub_snapshot` — подписка окна на push-события состояния
- `hub_watch` — подписка окна на push-события состояния
- `hub_refresh` — подписка окна на push-события состояния
- `block_check_start` — результаты приходят push-событиями окна; в CLI то же делает `chimera check list <список>`
- `chebur_check_start` — результаты приходят push-событиями окна; в CLI то же делает `chimera check list <список>`

## Команды подробно

### status

Что работает сейчас.

#### `chimera status`

Состояние приложения и модулей: обход, прокси, Telegram-прокси, hosts. Уровень: чтение.

```
chimera status
chimera status --json
```

### start

Запустить Chimera без окна (в трее).

#### `chimera start`

Запустить Chimera без окна, в трее. Права администратора запросит сама программа. Уровень: изменение приложения.

```
chimera start
```

### tui

Клавиатурное терминальное меню (стрелки/WASD, живое состояние)..

#### `chimera tui [--simple]`

Клавиатурный терминальный интерфейс: Обзор, Стратегии, Списки, Прокси, Hosts, DNS, Telegram, Логи, Настройки. Стрелки/WASD выбирают строку, Enter/D выполняют действие, Esc/A возвращают в меню. Цифры 1–9 выбирают пункт текущего меню; Ctrl+1–9 открывают раздел. E в списках открывает редактор в терминале: Ctrl+S сохраняет, Esc оставляет черновик. Ctrl+E разбирает маршрут сайта. Мышь отключена. Подключается к Chimera (не запущена — поднимет её без окна); выход (q) Chimera не останавливает. Без терминала или Textual — простое меню. --simple — меню цифрами со своим Api. Двоеточие открывает строку команд с историей и результатами. Уровень: изменение приложения. Работает и без запущенной Chimera.

- `--simple` — простое меню цифрами вместо полноэкранного

```
chimera tui
chimera tui --simple
```

### stop

Закрыть Chimera.

#### `chimera stop`

Закрыть Chimera и погасить её модули. Уровень: изменение приложения.

```
chimera stop
```

### restart

Перезапустить Chimera.

#### `chimera restart`

Перезапустить Chimera. Уровень: изменение приложения.

```
chimera restart
```

### version

Версия программы и протокола.

#### `chimera version`

Версия программы и версия протокола командной строки. Уровень: чтение. Работает и без запущенной Chimera.

```
chimera --version
chimera version --json
```

### update

Обновление Chimera.

#### `chimera update state`

Состояние обновления: текущая и найденная версии, стадия. Уровень: чтение.

```
chimera update state
```

#### `chimera update check`

Проверить, вышла ли новая версия. Уровень: чтение.

```
chimera update check
```

#### `chimera update install`

Скачать, проверить и установить найденную версию; программа перезапустится. Уровень: изменение системы.

```
chimera update check && chimera update install
```

### autostart

Запуск Chimera вместе с Windows.

#### `chimera autostart state`

Включён ли запуск вместе с Windows. Уровень: чтение.

```
chimera autostart state
```

#### `chimera autostart set <on|off>`

Включить или выключить запуск вместе с Windows (нужны права администратора). Уровень: изменение системы.

- `значение` — on или off

```
chimera autostart set on
```

### discord

Очистка кэша Discord.

#### `chimera discord clear-cache`

Очистить кэш Discord (Discord должен быть закрыт). Уровень: изменение приложения.

```
chimera discord clear-cache
```

### sources

Внешние источники: zapret2, стратегии Flowseal и др..

#### `chimera sources versions`

Локальные версии внешних источников (без сети). Уровень: чтение.

```
chimera sources versions
```

#### `chimera sources check [имя]`

Сверить версии источников с GitHub (все или один). Уровень: чтение.

- `имя` — источник; без имени — все

```
chimera sources check
chimera sources check zapret2
```

#### `chimera sources update <имя>`

Подтянуть свежую версию источника (git fetch + checkout). Уровень: изменение системы.

- `имя` — источник из `chimera sources versions`

```
chimera sources update zapret2
```

### config

Настройки программы (config.json).

#### `chimera config get [ключ]`

Показать настройки программы: все или одну. Уровень: чтение. Работает и без запущенной Chimera.

- `ключ` — имя настройки; без него — все

```
chimera config get
chimera config get update_channel
```

#### `chimera config set <ключ> <значение>`

Изменить настройку. Доступно то, что меняет окно: ui_backend, auto_elevate, close_to_tray, update_channel, update_check, theme (system, light или dark), lang (auto, ru или en). Остальное — правкой config.json. Уровень: изменение приложения. Работает и без запущенной Chimera.

- `ключ` — имя настройки
- `значение` — true/false, число или строка

```
chimera config set update_channel beta
chimera config set close_to_tray false
chimera config set theme dark
```

#### `chimera config export [--sections <sections>] [--file <file>]`

Собрать конфиг для отправки: разделы --sections (по умолчанию переносимые: lists,proxy,hosts,dns,telegram; winws зависит от провайдера и включается явно). Ссылка прокси и секреты не входят. --file — записать в файл. Уровень: чтение.

- `--sections` — разделы через запятую
- `--file` — записать в файл

```
chimera config export --file my.chimera
chimera config export --sections proxy,lists
```

#### `chimera config import-preview <файл>`

Показать, что изменит чужой конфиг (файл или `-` для stdin): применится, пропущено, требует подтверждения. Ничего не меняет. Уровень: чтение.

- `файл` — файл конфига или - для stdin

```
chimera config import-preview friend.chimera
```

#### `chimera config import <файл> [--sections <sections>] [--confirm]`

Применить чужой конфиг (разделы --sections, по умолчанию все, кроме зависящих от провайдера). Сначала смотрите `config import-preview`. Чужие серверы DNS/hosts и домены Telegram — только с --confirm. Перед применением файлы копируются в data/backups. Уровень: изменение приложения.

- `файл` — файл конфига или - для stdin
- `--sections` — разделы через запятую
- `--confirm` — разрешить чужие серверы DNS/hosts и домены Telegram

```
chimera config import friend.chimera --sections proxy,lists
```

#### `chimera config appearance`

Текущее оформление. Уровень: чтение.

```
chimera config appearance --json
```

#### `chimera config appearance-preview <settings>`

Предпросмотр оформления без сохранения. Уровень: чтение.

- `settings` — JSON: theme и appearance.

```
chimera config appearance-preview '{"theme":"dark","appearance":{"palette":"dracula"}}' --json
```

#### `chimera config appearance-apply <settings>`

Применить оформление и сохранить снимок. Уровень: изменение приложения.

- `settings` — JSON: theme и appearance.

```
chimera config appearance-apply '{"appearance":{"radius":"rounded"}}'
```

#### `chimera config appearance-refresh`

Обновить каталог тем с GitHub. Уровень: изменение приложения.

```
chimera config appearance-refresh
```

#### `chimera config backup`

Создать ручной снимок всех настроек Chimera и пользовательских списков. Не меняет работающие модули. Локальный снимок содержит секреты; вывод показывает только его имя и разделы. Уровень: изменение приложения.

```
chimera config backup
chimera config backup --json
```

#### `chimera config verify <домены…>`

Проверить сайты и сохранить полный проверенный снимок Уровень: изменение приложения.

- `домены` — От 1 до 6 доменов через запятую; все должны ответить успешно

```
chimera config verify youtube.com,discord.com
```

#### `chimera config verified`

Показать последний проверенный снимок и его сайты Уровень: чтение.

```
chimera config verified --json
```

#### `chimera config backups`

Список локальных снимков конфигурации, включая снимки перед импортом. Значения секретов не выводятся. Уровень: чтение.

```
chimera config backups
chimera config backups --json
```

#### `chimera config compare <first> <second>`

Сравнить два сохранённых снимка без применения настроек. Уровень: чтение.

- `first` — ID первого снимка (исходное состояние).
- `second` — ID второго снимка (изменённое состояние).

```
chimera config compare 20260930-120000-001-manual 20260930-130000-001-manual --json
```

#### `chimera config restore-preview <id>`

Проверить снимок и показать, какие настройки и списки восстановятся. Ничего не меняет; секреты скрыты. Уровень: чтение.

- `id` — имя каталога снимка из config backups, без пути

```
chimera config restore-preview 20260930-120000-001-import
```

#### `chimera config restore <id> [--confirm]`

Восстановить локальный снимок с --confirm. Перед изменениями сохраняется текущая конфигурация, настройки применяются к работающим модулям; при ошибке выполняется откат. Ранее остановленные модули не запускаются. Уровень: изменение системы.

- `id` — имя каталога снимка из config backups, без пути
- `--confirm` — подтвердить замену настроек и применение к работающим модулям

```
chimera config restore 20260930-120000-001-import --confirm
```

### lang

Язык программы.

#### `chimera lang show`

Язык программы: что выбрано в настройках, какой язык действует сейчас и какой у системы. Уровень: чтение. Работает и без запущенной Chimera.

```
chimera lang show
chimera lang show --json
```

#### `chimera lang set <auto|ru|en>`

Выбрать язык программы: auto (как в Windows), ru или en. Флаг `--lang` и переменная CHIMERA_LANG приоритетнее. Уровень: изменение приложения. Работает и без запущенной Chimera.

- `значение` — auto, ru или en

```
chimera lang set en
chimera lang set auto
```

#### `chimera lang catalog [ru|en]`

Каталог текстов языка целиком (для окна и проверок): ключ → текст. Без языка — текущий. Уровень: чтение. Работает и без запущенной Chimera.

- `язык` — ru или en; без него — текущий

```
chimera lang catalog en --json
```

### winws

Обход DPI (zapret2 / winws2).

#### `chimera winws state`

Состояние обхода: запущен ли, стратегия, списки, ошибка, версия. Уровень: чтение.

```
chimera winws state
```

#### `chimera winws strategies`

Список доступных стратегий. Уровень: чтение.

```
chimera winws strategies --json
```

#### `chimera winws start [стратегия]`

Запустить стратегию. Без имени — последнюю использованную. Уровень: изменение системы.

- `стратегия` — id из `chimera winws strategies`; по умолчанию последняя

```
chimera winws start
chimera winws start alt2
```

#### `chimera winws stop`

Остановить обход. Уровень: изменение системы.

```
chimera winws stop
```

#### `chimera winws autostart <on|off>`

Запускать стратегию при старте Chimera. Уровень: изменение приложения.

- `значение` — on или off

```
chimera winws autostart on
```

#### `chimera winws lists [списки…]`

Какие списки доменов гнать через обход (без имён — очистить). Применяется сразу. Уровень: изменение приложения.

- `списки` — имена списков

```
chimera winws lists youtube discord
```

#### `chimera winws filters`

Состояние фильтров: game, ipset, fake-блобы. Уровень: чтение.

```
chimera winws filters
```

#### `chimera winws game <off|all|tcp|udp> [--tcp <tcp>] [--udp <udp>]`

Игровой фильтр: off, all, tcp или udp; порты — необязательно. Уровень: изменение системы.

- `режим` — режим
- `--tcp` — диапазон TCP-портов
- `--udp` — диапазон UDP-портов

```
chimera winws game udp
chimera winws game all --tcp 1024-65535
```

#### `chimera winws ipset <none|any|loaded>`

Режим ipset: none, any или loaded. Уровень: изменение приложения.

- `режим` — режим

```
chimera winws ipset loaded
```

#### `chimera winws ipset-update`

Скачать свежий список подсетей (ipset). Уровень: изменение системы.

```
chimera winws ipset-update
```

#### `chimera winws fake <слот> <блоб>`

Подставить fake-блоб в слот (discord или game). Уровень: изменение приложения.

- `слот` — слот из `chimera winws filters`
- `блоб` — имя блоба

```
chimera winws fake discord quic_initial_www_google_com
```

### proxy

Прокси на sing-box.

#### `chimera proxy state`

Состояние прокси: запущен ли, режим, списки, число доменов, ядро. Уровень: чтение.

```
chimera proxy state
```

#### `chimera proxy start`

Запустить прокси (sing-box). Уровень: изменение системы.

```
chimera proxy start
```

#### `chimera proxy stop`

Остановить прокси. Уровень: изменение системы.

```
chimera proxy stop
```

#### `chimera proxy mode <pac|split|tun>`

Режим прокси: pac (без админа), split (выборочный TUN) или tun (весь трафик). Уровень: изменение системы.

- `режим` — режим

```
chimera proxy mode pac
```

#### `chimera proxy link [ссылка] [--clear]`

Задать ссылку прокси (vless://, trojan://, ss://, vmess://). `-` — прочитать из stdin, `--clear` — удалить. Уровень: изменение приложения.

- `ссылка` — ссылка или `-`
- `--clear` — удалить ссылку

```
chimera proxy link vless://...
echo vless://... | chimera proxy link -
chimera proxy link --clear
```

#### `chimera proxy lists [списки…]`

Какие списки идут через прокси (без имён — очистить). Применяется сразу. Уровень: изменение приложения.

- `списки` — имена списков

```
chimera proxy lists youtube telegram
```

#### `chimera proxy apps [приложения…]`

Приложения для выборочного TUN, имена образов (Discord.exe). Без имён — очистить. Уровень: изменение приложения.

- `приложения` — Discord.exe …

```
chimera proxy apps Discord.exe chrome.exe
```

#### `chimera proxy apps-running`

Запущенные сейчас программы пользователя (для выбора в выборочный TUN). Уровень: чтение.

```
chimera proxy apps-running
```

#### `chimera proxy autostart <on|off>`

Запускать прокси при старте Chimera. Уровень: изменение приложения.

- `значение` — on или off

```
chimera proxy autostart on
```

#### `chimera proxy core-download`

Скачать ядро sing-box (пиннутая версия, с проверкой SHA256). Уровень: изменение приложения.

```
chimera proxy core-download
```

### tg

Telegram-прокси.

#### `chimera tg state`

Состояние Telegram-прокси и его настройки. Уровень: чтение.

```
chimera tg state
```

#### `chimera tg start`

Запустить Telegram-прокси. Уровень: изменение приложения.

```
chimera tg start
```

#### `chimera tg stop`

Остановить Telegram-прокси. Уровень: изменение приложения.

```
chimera tg stop
```

#### `chimera tg stats`

Счётчики работающего Telegram-прокси. Уровень: чтение.

```
chimera tg stats
```

#### `chimera tg link`

Ссылка tg://proxy для подключения Telegram. Уровень: чтение.

```
chimera tg link
```

#### `chimera tg config [--host <host>] [--port <port>] [--secret <secret>] [--autostart <autostart>]`

Изменить адрес, порт, секрет или автозапуск (остальное не меняется). Уровень: изменение приложения.

- `--host` — адрес; 0.0.0.0 — открыть для устройств в сети
- `--port` — порт
- `--secret` — секрет из 32 hex-символов
- `--autostart` — on или off

```
chimera tg config --port 1443
chimera tg config --host 0.0.0.0
```

#### `chimera tg regen-secret`

Сгенерировать новый секрет (старая ссылка перестанет работать). Уровень: изменение приложения.

```
chimera tg regen-secret
```

#### `chimera tg advanced <настройки…>`

Продвинутые настройки ядра: ключ=значение (значение — JSON или строка). Уровень: изменение приложения.

- `настройки` — ключ=значение …

```
chimera tg advanced fake_tls_domain=example.com
chimera tg advanced fallback_cfproxy=false
```

#### `chimera tg check-update`

Проверить обновление ядра Telegram-прокси. Уровень: чтение.

```
chimera tg check-update
```

### hosts

Подмена IP в системном hosts.

#### `chimera hosts state`

Состояние подмены hosts: применена ли, сколько записей. Уровень: чтение.

```
chimera hosts state
```

#### `chimera hosts overview`

Всё по hosts: провайдеры, списки, привязки, состояние. Уровень: чтение.

```
chimera hosts overview --json
```

#### `chimera hosts on`

Включить подмену hosts (привязки сохраняются). Уровень: изменение системы.

```
chimera hosts on
```

#### `chimera hosts off`

Выключить подмену hosts: блок из файла убирается, привязки остаются. Уровень: изменение системы.

```
chimera hosts off
```

#### `chimera hosts assign [привязки…] [--replace]`

Привязать списки к провайдерам: провайдер=список,список (пусто — снять). Меняются только указанные провайдеры; --replace заменяет все привязки. Уровень: изменение системы.

- `привязки` — провайдер=список,список …
- `--replace` — заменить все привязки

```
chimera hosts assign comss=youtube,discord
chimera hosts assign xbox=
```

#### `chimera hosts provider-add <имя> <doh> <серверы…>`

Добавить hosts-провайдера (имя, DoH-адрес, серверы). Уровень: изменение приложения.

- `имя` — str
- `doh` — адрес DoH или - 
- `серверы` — IP-адреса

```
chimera hosts provider-add my https://dns.example/dns-query 1.2.3.4
```

#### `chimera hosts provider-delete <id>`

Удалить hosts-провайдера. Уровень: изменение приложения.

- `id` — id провайдера

```
chimera hosts provider-delete my
```

### dns

Системный DNS и DNS-провайдеры.

#### `chimera dns state`

Адаптеры, их текущий DNS и провайдеры. Уровень: чтение.

```
chimera dns state
```

#### `chimera dns ping [id]`

Пинг DNS-провайдеров: всех или одного. Уровень: чтение.

- `id` — провайдер; без него — все

```
chimera dns ping
```

#### `chimera dns probe <id>`

Проверить, отвечает ли провайдер на «обходные» и рекламные домены. Уровень: чтение.

- `id` — id провайдера

```
chimera dns probe cloudflare
```

#### `chimera dns probe-config [--bypass <bypass>] [--ad <ad>]`

Домены пробы: показать, либо задать --bypass и --ad. Уровень: изменение приложения.

- `--bypass` — домен «обходной» пробы
- `--ad` — домен рекламной пробы

```
chimera dns probe-config
chimera dns probe-config --bypass rutracker.org
```

#### `chimera dns set <адаптер> <провайдер>`

Поставить DNS-провайдера на адаптер (нужны права администратора). Уровень: изменение системы.

- `адаптер` — номер адаптера из `chimera dns state`
- `провайдер` — id провайдера

```
chimera dns set 12 cloudflare
```

#### `chimera dns reset <адаптер>`

Вернуть DNS адаптера на автоматический (DHCP). Уровень: изменение системы.

- `адаптер` — номер адаптера из `chimera dns state`

```
chimera dns reset 12
```

#### `chimera dns provider-add <имя> <серверы…> [--ipv6 <ipv6>] [--doh <doh>] [--dot <dot>] [--unblock] [--filtering]`

Добавить DNS-провайдера. Уровень: изменение приложения.

- `имя` — str
- `серверы` — IPv4-адреса
- `--ipv6` — IPv6-адреса через запятую
- `--doh` — адрес DoH
- `--dot` — имя DoT
- `--unblock` — разблокирующий
- `--filtering` — с фильтрацией

```
chimera dns provider-add my 9.9.9.9 149.112.112.112 --doh https://dns.quad9.net/dns-query
```

#### `chimera dns provider-delete <id>`

Удалить DNS-провайдера. Уровень: изменение приложения.

- `id` — id провайдера

```
chimera dns provider-delete my
```

#### `chimera dns trial <адаптер> <провайдер> [--seconds <seconds>]`

Поставить DNS с автооткатом: не подтвердите за --seconds секунд — вернётся прежний. Уровень: изменение системы.

- `адаптер` — номер адаптера из `chimera dns state`
- `провайдер` — id провайдера
- `--seconds` — секунд на подтверждение (5–120)

```
chimera dns trial 12 cloudflare
chimera dns trial 12 cloudflare --seconds 30
```

#### `chimera dns trial-confirm [адаптер]`

Оставить новый DNS после `dns trial`; без адаптера — все ожидающие. Уровень: изменение приложения.

- `адаптер` — номер адаптера; без него — все

```
chimera dns trial-confirm 12
```

#### `chimera dns trial-revert [адаптер]`

Вернуть прежний DNS сразу, не дожидаясь таймера. Уровень: изменение системы.

- `адаптер` — номер адаптера; без него — все

```
chimera dns trial-revert 12
```

#### `chimera dns record-start`

Начать запись доменов сайта: запоминает имена в кэше DNS Windows (кэш сбрасывается, если есть права администратора). Уровень: изменение приложения.

```
chimera dns record-start
```

#### `chimera dns record-stop`

Закончить запись: домены, появившиеся с начала, по основным доменам; трекеры помечены. Откройте нужный сайт между start и stop. Уровень: изменение приложения.

```
chimera dns record-start
chimera dns record-stop --json
```

### panic

Выключить всё разом: обход, прокси, Telegram, hosts, DNS, службу.

#### `chimera panic`

Выключить всё разом: обход, прокси, Telegram-прокси, службу, подмену hosts; вернуть DNS на адаптерах, где его ставила Chimera. Шаги независимы, сбой одного не мешает остальным. Только по просьбе пользователя. Уровень: изменение системы.

```
chimera panic
```

### doctor

Диагностика: почему обход может не работать.

#### `chimera doctor [--report]`

Диагностика: права, драйвер WinDivert, порты, чужие процессы, прокси в системе. --report даёт Markdown для issue (ссылки прокси и секреты скрыты). Ничего не меняет. Уровень: чтение.

- `--report` — отчёт в Markdown

```
chimera doctor
chimera doctor --report
chimera doctor --json
```

### lists

Списки доменов.

#### `chimera lists show [имя]`

Списки с числом доменов и подключениями; с именем — содержимое списка. Уровень: чтение. Работает и без запущенной Chimera.

- `имя` — список; без него — все

```
chimera lists show
chimera lists show youtube
```

#### `chimera lists save <имя> [--file <file>]`

Записать список целиком из файла (--file) или stdin. Уровень: изменение приложения. Работает и без запущенной Chimera.

- `имя` — список
- `--file` — файл со списком; без него — stdin

```
chimera lists save youtube --file youtube.txt
```

#### `chimera lists create <имя>`

Создать пустой список. Уровень: изменение приложения. Работает и без запущенной Chimera.

- `имя` — латиница, цифры, . - _

```
chimera lists create games
```

#### `chimera lists delete <имя>`

Удалить список. Уровень: изменение приложения.

- `имя` — str

```
chimera lists delete games
```

#### `chimera lists rename <старое> <новое>`

Переименовать список вместе со ссылками на него. Уровень: изменение приложения.

- `старое` — str
- `новое` — str

```
chimera lists rename games play
```

#### `chimera lists add <имя> <домены…>`

Добавить домены в список (список создаётся, если его нет). Применяется сразу. Уровень: изменение приложения. Работает и без запущенной Chimera.

- `имя` — str
- `домены` — домены или подсети

```
chimera lists add youtube ytimg.com googlevideo.com
```

#### `chimera lists remove <имя> <домены…>`

Убрать домены из списка. Уровень: изменение приложения. Работает и без запущенной Chimera.

- `имя` — str
- `домены` — домены или подсети

```
chimera lists remove youtube ytimg.com
```

#### `chimera lists validate [имя]`

Проверить файл списка, ничего не меняя: кодировка, синтаксис доменов и подсетей, дубликаты. Без имени — все списки. Есть ошибки — код возврата 1. Уровень: чтение. Работает и без запущенной Chimera.

- `имя` — список; без него — все

```
chimera lists validate
chimera lists validate youtube --json
```

#### `chimera lists apply [имя]`

Применить список к обходу, прокси и hosts сейчас (без имени — все). Обычно не нужно: правку lists/*.txt на диске работающая программа подхватывает сама, а сохранение через `lists save` применяется сразу. Нужна работающая Chimera с окном или в трее. Уровень: изменение приложения.

- `имя` — список; без него — все

```
chimera lists apply
chimera lists apply youtube
```

### check

Открывается ли сайт и заблокирован ли он.

#### `chimera check site <домен> [--only <only>]`

Проверить один домен: доступность с этого компьютера и наличие в реестре блокировок. Уровень: чтение. Работает и без запущенной Chimera.

- `домен` — домен или адрес
- `--only` — только local или registry

```
chimera check discord.com
chimera check site discord.com --only local
```

#### `chimera check list <список> [--only <only>]`

Проверить все домены списка (параллельно), как «Проверить список» в окне. Уровень: чтение. Работает и без запущенной Chimera.

- `список` — имя списка
- `--only` — только local или registry

```
chimera check list discord
```

#### `chimera check status`

Состояние сервиса реестра блокировок (версия, дата обновления). Уровень: чтение.

```
chimera check status
```

### logs

Последние строки логов модулей.

#### `chimera logs <winws|proxy|tg> [--tail <tail>]`

Последние строки лога модуля: winws, proxy или tg. Уровень: чтение. Работает и без запущенной Chimera.

- `модуль` — модуль
- `--tail` — сколько последних строк (по умолчанию 40)

```
chimera logs winws
chimera logs proxy --tail 100
```

### service

Фоновая служба Windows.

#### `chimera service <install|uninstall|start|stop|status|run> [параметры…]`

Фоновая служба: install, uninstall, start, stop, status, run (как `main.py service`). Уровень: изменение системы. Работает и без запущенной Chimera.

- `команда` — действие
- `параметры` — например --dry-run

```
chimera service status
chimera service install --dry-run
```

### path

Команда chimera в PATH пользователя.

#### `chimera path show`

Есть ли папка программы в PATH пользователя. Уровень: чтение. Работает и без запущенной Chimera.

```
chimera path show
```

#### `chimera path add`

Добавить папку программы в PATH пользователя (после этого `chimera` работает из любой папки). Уровень: изменение приложения. Работает и без запущенной Chimera.

```
chimera path add
```

#### `chimera path remove`

Убрать папку программы из PATH пользователя. Уровень: изменение приложения. Работает и без запущенной Chimera.

```
chimera path remove
```

### docs

Документация этой версии: команды, папки и файлы, формат вывода.

#### `chimera docs [commands|layout|output]`

Документация этой версии программы. Темы: commands (команды), layout (папки и файлы), output (коды возврата и формат --json). Без темы — оглавление; с --json — всё в машинном виде. Уровень: чтение. Работает и без запущенной Chimera.

- `тема` — тема

```
chimera docs
chimera docs layout
chimera docs --json
```

### agent-info

Сводка для агентов: версии, команды с уровнями, пути (`--json`).

#### `chimera agent-info`

Сводка для агентов: версия программы и протокола, совместимая версия скилла, команды с уровнями, пути к данным. Для машинного разбора — с --json. Уровень: чтение. Работает и без запущенной Chimera.

```
chimera agent-info --json
```

### trial

Пробное применение с проверкой и автооткатом..

#### `chimera trial state`

Текущая проба, результаты проверки и последняя завершённая проба. Исходное состояние и секреты не выдаются. Уровень: чтение.

```
chimera trial state --json
```

#### `chimera trial start <strategy|hosts|tun> <target> [--seconds <seconds>] [--domains <domains>]`

Пробно применить стратегию, выключатель hosts или режим TUN. Проверяет контрольные сайты; при сбое или без подтверждения возвращает исходное состояние. Одна проба за раз; другие изменения блокируются до её завершения. Уровень: изменение системы.

- `kind` — strategy, hosts или tun
- `target` — ID стратегии, on/off для hosts или split/tun
- `--seconds` — время подтверждения: 15–300 секунд
- `--domains` — контрольные домены через запятую (до 6); по умолчанию example.com,cloudflare.com

```
chimera trial start strategy general --seconds 60 --domains example.com,discord.com
chimera trial start hosts on
chimera trial start tun tun
```

#### `chimera trial confirm <id>`

Оставить настройки после успешной проверки. Нужен ID текущей пробы; просроченную пробу подтвердить нельзя. Уровень: изменение приложения.

- `id` — ID текущей пробы из trial state

```
chimera trial confirm 0123456789abcdef
```

#### `chimera trial revert <id>`

Вернуть исходные настройки и состояние запуска модуля. При ошибке сохраняет данные для повторного отката. Уровень: изменение системы.

- `id` — ID текущей пробы из trial state

```
chimera trial revert 0123456789abcdef
```

### explain

Почему адрес попал в этот маршрут.

#### `chimera explain <домен> [--app <app>]`

Объяснить правила для домена или IP: списки, DPI, PAC/TUN, приложение и записи hosts. Читает настройки локально, не делает DNS-запросов и ничего не меняет. Уровень: чтение.

- `домен` — домен, IP или HTTP(S)-адрес без учётных данных
- `--app` — имя процесса, например Discord.exe; для выборочного TUN

```
chimera explain youtube.com
chimera explain 192.168.1.1 --app chrome.exe
chimera explain discord.com --app Discord.exe --json
```

### providers

Провайдеры DNS и hosts: одно место настройки, вкладки DNS и Hosts выбирают из них..

#### `chimera providers list`

Все провайдеры, включая скрытые встроенные, и сколько списков hosts на каждом. Уровень: чтение.

```
chimera providers list
chimera providers list --json
```

#### `chimera providers add <имя> [серверы…] [--ipv6 <ipv6>] [--doh <doh>] [--dot <dot>] [--unblock] [--filtering]`

Добавить провайдера. Уровень: изменение приложения.

- `имя` — str
- `серверы` — IPv4-адреса
- `--ipv6` — IPv6-адреса через запятую
- `--doh` — адрес DoH
- `--dot` — имя DoT
- `--unblock` — умеет обходить блокировки (для hosts)
- `--filtering` — фильтрует рекламу или угрозы

```
chimera providers add Quad9 9.9.9.9 149.112.112.112 --doh https://dns.quad9.net/dns-query
chimera providers add Мой --doh https://dns.example/dns-query --unblock
```

#### `chimera providers edit <id> <имя> [серверы…] [--ipv6 <ipv6>] [--doh <doh>] [--dot <dot>] [--unblock] [--filtering]`

Изменить своего провайдера: имя и адреса задаются заново целиком. Уровень: изменение приложения.

- `id` — id провайдера
- `имя` — str
- `серверы` — IPv4-адреса
- `--ipv6` — IPv6-адреса через запятую
- `--doh` — адрес DoH
- `--dot` — имя DoT
- `--unblock` — умеет обходить блокировки (для hosts)
- `--filtering` — фильтрует рекламу или угрозы

```
chimera providers edit my Quad9 9.9.9.9 149.112.112.112
```

#### `chimera providers delete <id>`

Удалить своего провайдера и его привязки hosts. Уровень: изменение приложения.

- `id` — id провайдера

```
chimera providers delete my
```

#### `chimera providers hide <id> [on|off]`

Скрыть встроенного провайдера со всех вкладок или вернуть его. Уровень: изменение приложения.

- `id` — id встроенного провайдера
- `hidden` — true — скрыть, false — вернуть

```
chimera providers hide google
chimera providers hide google false
```

## Файлы

| Путь | Что это |
|---|---|
| `config.json` | можно править: Настройки программы. Менять командой `chimera config set` (часть ключей — только правкой файла). |
| `lists/*.txt` | можно править: Списки доменов и подсетей, по одной записи в строке, # — комментарий. Команды `chimera lists …`. Правку файла напрямую работающая программа подхватывает сама за пару секунд (создание, изменение, удаление); проверить файл: `chimera lists validate`. |
| `strategies/*.txt` | генерируется, не править: Стратегии winws2, портируются из Flowseal (tools/port_flowseal.py). Не править. |
| `strategies/hostlists/list-general-user.txt` | генерируется, не править: Собирается из выбранных у обхода списков. Не править. |
| `strategies/hostlists/ipset-user.txt` | генерируется, не править: Подсети из выбранных списков. Не править. |
| `strategies/hostlists/list-exclude-user.txt` | можно править: Домены-исключения для обхода. Править только по просьбе пользователя. |
| `strategies/hostlists/ipset-exclude-user.txt` | можно править: Подсети-исключения для обхода. Править только по просьбе пользователя. |
| `strategies/hostlists/ipset-all.txt` | можно править: Общий список подсетей (режим ipset). Меняется командами `chimera winws ipset …`. |
| `data/winws.json` | внутреннее состояние: Последняя стратегия, выбранные списки, автозапуск обхода. Менять командами `chimera winws …`. |
| `data/proxy.json` | секрет: Ссылка прокси (учётные данные), режим, списки, приложения. Не читать и не показывать. |
| `data/tgproxy.json` | секрет: Порт, секрет и параметры Telegram-прокси. Не читать и не показывать. |
| `data/hosts.json` | внутреннее состояние: Привязки списков к провайдерам hosts, фоновые опции. Команды `chimera hosts …`. |
| `data/dns_providers.user.json` | внутреннее состояние: DNS-провайдеры, добавленные пользователем. Команды `chimera dns provider-…`. |
| `data/singbox-config.json` | генерируется, не править: Конфиг sing-box. Пересобирается программой. |
| `data/singbox-domains.json` | генерируется, не править: Домены выбранных у прокси списков (файл правил sing-box). Пересобирается. |
| `data/singbox-ips.json` | генерируется, не править: Подсети выбранных у прокси списков. Пересобирается. |
| `data/proxy.pac` | генерируется, не править: PAC-файл режима pac. Пересобирается. |
| `data/logs/*.log` | лог, только читать: Логи модулей (winws, proxy, tgproxy, hosts, service, update). Читать: `chimera logs <модуль>`. |
| `data/changes.log` | лог, только читать: Журнал изменений: время, источник (`cli` — команда, `file` — правка списка на диске), команда, результат (`ok` или `error`). |
| `data/control.json` | секрет: Порт и токен канала управления. Агенту читать не нужно, не показывать. |
| `data/backups/` | секрет: Локальные снимки до импорта/восстановления (последние 10). Могут содержать секреты; не публиковать. Чтение и восстановление: chimera config backups / restore-preview / restore. |
| `data/trial.json` | внутреннее состояние: Исходное состояние незавершённой пробы. Не править; chimera trial state / confirm / revert. |
| `bin/` | внешнее, не править: Бинарники (sing-box, winws2). Не править. |
| `upstream/` | внешнее, не править: Внешние проекты (сабмодули). Не править. |
