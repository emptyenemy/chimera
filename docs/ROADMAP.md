# Roadmap

## Готово

- **UI (PySide6 / QWebEngineView)** — графический интерфейс, выбор режима через `config.json`.
- **Вкладка Hosts** — наборы подмен IP в системном hosts-файле:
  - тип `static` — готовый список (руками или по URL hosts-файла, напр. malw hosts);
  - тип `dns` — DNS-провайдер (XBOX / Comss / Malw): домены из списков резолвятся через его DoH/UDP, полученные IP пишутся в hosts;
  - применённый набор пишется блоком между маркерами `# >>> chimera-hosts >>>` — снимается/обновляется без следов;
  - чекер: TCP + TLS-handshake по каждой записи (OK / TCP / FAIL + пинг в мс);
  - после записи в hosts автоматически `ipconfig /flushdns`.
- **Вкладка DNS (DNS Jumper внутри программы)** — переключение системного DNS:
  - провайдеры в `modules/dns_jumper/providers.json` (Cloudflare, Google, Quad9, AdGuard, Яндекс, OpenDNS, XBOX, Malw);
  - список всех адаптеров со статусом/IP/текущим DNS, выбор адаптера;
  - пинг всех серверов параллельно, применение/сброс на DHCP через `Set-DnsClientServerAddress`.
- **Списки доменов** (`lists/*.txt`) — единый источник для всех модулей: openai, anthropic, google-gemini, microsoft-copilot, deepl, spotify, notion, youtube, discord.
- **Вкладка Telegram** — [flowseal/tg-ws-proxy](https://github.com/flowseal/tg-ws-proxy) как модуль:
  - ядро (пакет `proxy`) импортируется из сабмодуля `upstream/tg-ws-proxy`, работает в фоновом потоке — без трея/окон апстрима;
  - host/port/secret настраиваются (хранятся в `modules/tgproxy/state.json`, не в git), секрет перегенерируется кнопкой;
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
  - первая портированная: **SIMPLE FAKE** из [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) (winws1 `--dpi-desync` → winws2 `--lua-desync`);
  - fake-блобы и hostlist'ы Flowseal лежат в `strategies/assets` и `strategies/hostlists`;
  - лаунчер `modules/winws`: сборка argv, старт/стоп winws2, вывод в лог, очистка при выходе;
  - версия zapret2 (тег сабмодуля) показывается в UI; **zapret2 обновлён до v1.0.2** (бандл `0e9e3fb` + сабмодуль, COMPAT_VER 6; фикс дефолта `--lua-gc` 60 мс → 60 сек, режет лишний CPU и на winws2). Бандл-коммит `e48e760→0e9e3fb` — force-push апстрима; winws2.exe и lua байт-в-байт те же, изменения только в blockcheck/arm64.

## В работе / дальше

- **Портировать остальные стратегии Flowseal** — general, ALT-серия, FAKE TLS AUTO и пр. (по образцу SIMPLE FAKE), + проверка вживую под админом.

- **Списки доменов как полноценная вкладка** — редактирование, включение/выключение списков для набора, и **разные транспорты на список**: один гнать через DNS-подмену, другой — через VPN/прокси, третий — через zapret. Списки = общий слой, поверх него правила маршрутизации.
- **Service-режим (3-й вариант запуска)** — старт как служба Windows, без окна и трея. `config.json` → `"interface": "service"`.
- **TUI-режим** — терминальный интерфейс. `config.json` → `"interface": "tui"`.
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
- `ui/` — PySide6-приложение (`app.py` = QWebChannel-мост к модулям, `web/` = фронт).
- Режим интерфейса: `config.json` → `"ui"` | `"tui"` | `"service"`.
- Транспорты (DNS-подмена / VPN / zapret) — поверх общих списков доменов, выбираются правилами.
