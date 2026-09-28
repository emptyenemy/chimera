# Roadmap

## Готово

- **UI (PySide6 / QWebEngineView, pywebview / WebView2 или вкладка в браузере)** — графический интерфейс, выбор режима и движка через `config.json` (`interface`, `ui_backend`). Вызовы фронта исполняются в фоновых потоках, окно не фризит на долгих операциях (опрос адаптеров, состояние прокси).
  - фронт — компоненты shadcn/ui (new-york, тёмная тема) на чистых HTML/CSS/JS без сборки: ядро `ui/web/js/core.js` (мост, стор, `morph()` — точечный патч DOM вместо перерисовки, роутер страниц, диалоги/тосты/меню/лог), дизайн-система `ui/web/css/base.css`, по файлу на страницу в `js/pages/` и `css/pages/`, иконки lucide спрайтом (`vendor/update-vendor.sh`);
  - состояние модулей фронт не опрашивает: его пушит хаб `ui/hub.py` (по потоку на источник, пуш только при изменении, ленивые источники — пока открыта их вкладка, после команды источник перечитывается сразу). Интерфейс рисует из стора и не ждёт бэкенд; тумблеры переключаются оптимистично и откатываются при ошибке;
  - проверка без окна — `tools/ui_preview.py` (сервер движка browser с настоящим Api, команды не исполняются) + `tools/ui_shot.mjs` (headless Edge по CDP: сценарий кликов, eval, скриншоты);
  - `browser` — своего окна нет: фронт отдаёт локальный HTTP-сервер (`ui/backend_browser.py`, только стандартная библиотека), страница открывается вкладкой в браузере по умолчанию. Мост — `POST /api` (тот же JSON-RPC) и long-poll `GET /events` вместо push'ей; доступ по одноразовому токену (адрес + cookie), потому что через мост доступно всё API. Вкладка закрыта дольше полутора минут — программа гасит свои процессы и выходит, как по закрытию окна.
- **Источники и обновления (Настройки)** — версии всех внешних компонентов в одном списке: сверка с апстримом по каждому отдельно или всех сразу (результаты приезжают по мере готовности — медленный ответ не держит остальные), кнопка «Обновить» в строке (`git fetch` + checkout тега / `reset --hard` для бандла; для стратегий Flowseal сразу перепорт `tools/port_flowseal.py`) и «Обновить всё». Пиннутые в коде версии (sing-box, шрифты) и Python кнопкой не трогаем — вместе с версией меняется схема конфига.
- **Вкладка Hosts** — наборы подмен IP в системном hosts-файле:
  - тип `dns` — DNS-провайдер (XBOX / Comss / Malw): домены из списков резолвятся через его DoH/UDP, полученные IP пишутся в hosts;
  - тип `static` (`modules/hosts/static_providers.py`) — готовый список записей из файла, без резолвинга; встроенный — «Flowseal (GitHub/Telegram/Discord)», читает `upstream/zapret-discord-youtube/.service/hosts` заново при каждом применении (обновление сабмодуля подхватывается само); нет сабмодуля рядом (собранный exe) — провайдер помечен `available: false` с причиной, без падений; в привязках (`assignments`) static-провайдер включается булевым значением, а не списком доменов, т.к. свои записи несёт сам;
  - применённый набор пишется блоком между маркерами `# >>> chimera-hosts >>>` — снимается/обновляется без следов;
  - чекер: TCP + TLS-handshake по каждой записи (OK / TCP / FAIL + пинг в мс);
  - после записи в hosts автоматически `ipconfig /flushdns`;
  - **фон** (`modules/hosts/background.py`, единый поток, `HostsManager.start_background()/stop_background()`, настройки в `data/hosts.json` → `background`, API `hosts_set_background`): автообновление — периодически (по умолчанию раз в 6 ч, выключаемо) перерезолвливает dns-привязки и переписывает блок только если IP реально сменился; чекер — периодически (по умолчанию раз в 15 мин) прогоняет применённые записи TCP+TLS параллельно и копит health (`hosts_state().health`: alive/total/ratio по каждой привязке); автопереключение (выключено по умолчанию) — если dns-привязка деградировала (<50% живых) два чекера подряд, переключает её на следующий живой провайдер из настроенного порядка, событие — в `hosts_state().last_switch` и `data/logs/hosts.log`.
- **Очистка кэша Discord** (`modules/discord.py`, API `discord_clear_cache`) — как одноимённый пункт `service.bat` у Flowseal: чистит `Cache`/`Code Cache`/`GPUCache` у Discord/PTB/Canary/Development в `%APPDATA%`; в отличие от `service.bat` процесс не закрывает сам — если вариант запущен, отменяет чистку целиком с понятной ошибкой (кого закрыть), не трогая остальные.
- **Вкладка DNS (DNS Jumper внутри программы)** — переключение системного DNS:
  - провайдеры в `modules/dns_jumper/providers.json` (Cloudflare, Google, Quad9, AdGuard, Яндекс, OpenDNS, XBOX, Malw);
  - список всех адаптеров со статусом/IP/текущим DNS, выбор адаптера;
  - пинг всех серверов параллельно, применение/сброс на DHCP через `Set-DnsClientServerAddress`.
- **Списки доменов** (`lists/*.txt`) — единый источник для всех модулей: openai, anthropic, google-gemini, microsoft-copilot, deepl, spotify, notion, youtube, discord.
- **Единая папка рантайм-данных** (`modules/paths.py`) — state.json/логи/сгенерированные конфиги всех модулей лежат в `data/` рядом с программой (`data/logs/` — логи), а не рядом с исходниками модулей; путь переопределяется `CHIMERA_DATA`. Рядом с exe, а не в `%APPDATA%`, — портативность и общий вид для будущего service-режима (работает от SYSTEM). Старые файлы переезжают автоматически при первом обращении.
- **Вкладка Telegram** — [flowseal/tg-ws-proxy](https://github.com/flowseal/tg-ws-proxy) как модуль:
  - ядро (пакет `proxy`) импортируется из сабмодуля `upstream/tg-ws-proxy`, работает в фоновом потоке — без трея/окон апстрима;
  - host/port/secret настраиваются (хранятся в `data/tgproxy.json`, не в git), секрет перегенерируется кнопкой;
  - запуск/остановка из UI, автозапуск вместе с программой, живая статистика соединений;
  - tg://proxy-ссылка: «Подключить в Telegram» / копирование;
  - версия ядра показывается в UI + проверка свежего релиза на GitHub;
  - обновление прокси: `git submodule update --remote upstream/tg-ws-proxy` — новые фишки подтягиваются без правок нашего кода.
- **Вкладка Блокировки** — проверка через [LowderPlay/cheburcheck](https://github.com/LowderPlay/cheburcheck), заблокирован ли домен в реестрах РКН:
  - публичный API cheburcheck.ru (свой код проверки не держим), версия сервиса и дата обновления реестра — в UI;
  - проверка одного домена или целого списка (стримингом), причина блокировки (реестр РКН / CDN / подсеть);
  - повтор при rate-limit (429), чтобы «лимит» вылезал реже.
- **Вкладка Стратегии (zapret2)** — запуск `winws2` с выбранной стратегией обхода DPI:
  - стратегии — `strategies/*.txt` (1 аргумент winws2 на строку, плейсхолдеры путей, метаданные в шапке);
  - портированы все стратегии [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) 1.10.3 (winws1 `--dpi-desync` → winws2 `--lua-desync`), генератор — `tools/port_flowseal.py`;
  - fake-блобы и hostlist'ы Flowseal лежат в `strategies/assets` и `strategies/hostlists`, синхронизируются тем же генератором (`sync_resources`) — кроме `*-user.txt` и `ipset-all.txt`;
  - **fake replace**: `ACTIVE_DISCORD_UDP.bin` / `ACTIVE_GAME_UDP.bin` — слоты, в которые копируется выбранный блоб (текущий определяется по SHA256, как в `service.bat`); выбор — селектами в карточке «Фильтры»;
  - лаунчер `modules/winws`: сборка argv, старт/стоп winws2, вывод в лог, очистка при выходе;
  - версия zapret2 (тег сабмодуля) показывается в UI; **zapret2 v1.0.5.2**, бандл `6eb463a` (`NFQWS2_COMPAT_VER=6` совпадает). Апстрим бандла регулярно делает force-push — обновление через `git reset --hard origin/master`, не `pull`.
- **Service-режим** (`config.json` → `"interface": "service"`, либо напрямую `python main.py service ...`, независимо от конфига) — фоновый процесс без окна, поднимает то, что помечено автозапуском (tg/winws/proxy), и держит между перезагрузками:
  - `modules/service.py`: install/uninstall/start/stop/status/run; «служба» — задача Планировщика (BootTrigger, принципал SYSTEM, `RunLevel=HighestAvailable`) по образцу `modules/autostart.py`, без pywin32 и без отдельной службы Windows (SCM);
  - остановка — именованное событие `Global\CHIMERA_Service_Stop` (ctypes), живость — именованный мьютекс `Global\CHIMERA_Service_Running` + pid-файл `data/service.pid` (только для отображения), лог — `data/logs/service.log`;
  - `autostart_modules()` — общая с UI логика автозапуска (раньше жила только в `Api._autostart_all`), делит её `Api.__init__`/`_autostart_all` и `service.run()`;
  - прокси в режиме **PAC** под сервисом не поднимается (пишет системный прокси в HKCU текущего пользователя, под SYSTEM это чужой куст) — только **TUN**, PAC пропускается с записью в лог;
  - единственный владелец процессов в паре UI+служба — служба: если она уже запущена (`app_info().service_running`), UI не поднимает свои автозапуски и не гасит процессы при закрытии окна;
  - фоновые задачи hosts (`HostsManager.start_background()/stop_background()`) сервис поднимает и гасит вместе с остальным.
- **TUI-режим** (`config.json` → `"interface": "tui"`) — терминальное меню без зависимостей (curses на Windows нет — только stdlib + ANSI-цвета): статус модулей, старт/стоп winws (поиск стратегии по подстроке), прокси (старт/стоп, PAC/TUN), Telegram-прокси (старт/стоп, tg://-ссылка), hosts вкл/выкл, DNS (провайдер на адаптер, сброс на DHCP), хвост логов. `tui/app.py`, работает через тот же класс `Api`, что и фронт.

## В работе / дальше

- **Списки доменов как полноценная вкладка** — редактирование, включение/выключение списков для набора, и **разные транспорты на список**: один гнать через DNS-подмену, другой — через VPN/прокси, третий — через zapret. Списки = общий слой, поверх него правила маршрутизации.
- **Вкладки в разработке**: Пресеты, Прокси (общий).
- **Hosts/DNS, развитие**: автообновление по расписанию, фоновый чекер, автопереключение на живой провайдер.

## Кроссплатформенность (Linux / macOS)

Цель — вынести всё, что зависит от ОС, в платформенный слой (`modules/platform/` с общим интерфейсом и реализациями win/linux/macos), а ядро (списки, парсеры, менеджеры) оставить общим. Текущий код прибит к Windows: PowerShell-командлеты, `winreg`, `ctypes.windll`, `tasklist`, бандл winws2. Готовность сильно разная по компонентам:

| Компонент | Windows | Linux | macOS | Что нужно сделать |
|---|---|---|---|---|
| Прокси (sing-box) | ✅ | ✅ | ✅ | бинарь под ОС/арх; системный прокси per-OS (`networksetup` / `gsettings`), TUN уже кроссплатформенный |
| Telegram-прокси | ✅ | ✅ | ✅ | готово — чистый Python asyncio |
| Проверки (cheburcheck / blockcheck) | ✅ | ✅ | ✅ | готово — HTTP и сокеты на stdlib |
| DoH/UDP-резолвер | ✅ | ✅ | ✅ | готово — stdlib |
| Hosts | ✅ | ⏳ | ⏳ | путь `/etc/hosts`, flush: `resolvectl flush-caches` (Linux) / `dscacheutil -flushcache; killall -HUP mDNSResponder` (macOS) |
| DNS-переключатель | ✅ | ⏳ | ⏳ | весь ОС-слой заново: `nmcli`/systemd-resolved (Linux), `networksetup` (macOS) вместо DnsClient-командлетов |
| Элевация прав | ✅ (UAC) | ⏳ | ⏳ | на Unix `os.geteuid()`; повышение через polkit/`sudo` (Linux) или `osascript ... administrator privileges` (macOS) |
| UI (PySide6/QWebEngineView) | ✅ | ⏳ | ⏳ | тот же бандленный Chromium на всех трёх ОС (Qt WebEngine) — переносится проще, чем на pywebview с его per-OS нативными вебвью |
| **DPI-обход (zapret)** | ✅ winws2 + WinDivert | ⏳ **nfqws2** | ❌ **под вопросом** | см. ниже |

**DPI-обход — главный затык и он разный по ОС.** На Windows перехват пакетов делает WinDivert; на Linux эквивалент — `nfqws2` через NFQUEUE + правила nftables/iptables (нужен root). Формат стратегий близок (`--lua-desync` тот же), но `--wf-*` (windivert-фильтр) на Linux заменяется правилами NFQUEUE — генератор стратегий и менеджер winws придётся развести по бэкендам. На **macOS нативного механизма нет**: divert-сокеты Apple фактически убрала, NFQUEUE отсутствует, готового zapret под мак нет — без своего kernel-extension (подпись Apple + SIP) полноценный winws на маке нереалистичен.

**Вывод по macOS:** реалистичная мак-версия — это «всё, кроме DPI-обхода»: прокси (sing-box) + Telegram-прокси + DNS + hosts + проверки. Именно прокси, а не winws, — рабочий способ обхода на маке.

Порядок внедрения: сначала платформенный слой + перенести «лёгкие» (прокси, tg, проверки) на Linux/macOS, затем hosts/DNS/элевация, в последнюю очередь — `nfqws2`-бэкенд для Linux.

## Архитектура

- `modules/` — вся логика (hosts, dns_jumper, domains, tgproxy, winws, cheburcheck). Интерфейсы — тонкие обёртки.
- `upstream/` — сабмодули внешних проектов (zapret2, tg-ws-proxy); их код импортируем/запускаем, но не правим — обновления через `git submodule update --remote`.
- `bin/zapret-win-bundle/` — бинарный бандл winws/winws2 + lua + WinDivert (в gitignore, тянется отдельно; держать COMPAT_VER одинаковым с сабмодулем zapret2).
- `strategies/` — портированные стратегии (`*.txt`), их fake-блобы (`assets/`) и hostlist'ы (`hostlists/`).
- `lists/` — списки доменов по сервисам, один файл = один сервис.
- `ui/` — `api.py` (все методы для фронта, без привязки к движку) + `hub.py` (пуш состояния модулей) + `backend_qt.py` / `backend_webview.py` / `backend_browser.py` (окно/вкладка и мост) + `web/` (фронт: `js/core.js`, `js/pages/*`, `css/base.css`). Мосты асинхронные: вызов уходит в фоновый поток, ответ возвращается по callId.
- Режим интерфейса: `config.json` → `"ui"` | `"tui"` | `"service"`; движок окна: `ui_backend` → `"pyside6"` | `"pywebview"` (в сборку exe входит только PySide6, см. `build.bat`).
- Транспорты (DNS-подмена / VPN / zapret) — поверх общих списков доменов, выбираются правилами.
