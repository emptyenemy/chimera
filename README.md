# CHIMERA

Графическая обёртка (Windows) над инструментами обхода DPI-блокировок в России (ТСПУ Роскомнадзора). Один интерфейс собирает несколько независимых способов разблокировки поверх общего слоя списков доменов:

- **Стратегии (zapret2 / winws2)** — обход DPI через [bol-van/zapret2](https://github.com/bol-van/zapret2), стратегии портированы из [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube);
- **Прокси (sing-box)** — выборочный VLESS/Trojan/SS/VMess только для доменов из списков (режим PAC без админа или TUN);
- **Telegram-прокси** — MTProto-прокси на базе [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy);
- **Hosts** — подмена IP в системном hosts через «разблокирующие» DNS (xbox / comss / malw);
- **DNS** — переключение системного DNS (DNS Jumper внутри программы);
- **Проверки** — блокировка по реестру РКН ([cheburcheck](https://github.com/LowderPlay/cheburcheck)) и локальная достижимость доменов.

## Стек

- **Python 3** + [PySide6](https://doc.qt.io/qtforpython/) (`QWebEngineView`, свой Chromium) — фронт на HTML/CSS/JS в `ui/web/`, бэкенд в `modules/`, мост — `QWebChannel`.
- Логика — в `modules/`, интерфейс (`ui/app.py`) — тонкий JS-мост. Внешние проекты подключены git-сабмодулями в `upstream/` и используются как есть.

```
.
├── main.py            # вход: UAC-элевация, выбор режима из config.json
├── config.json        # interface (ui|tui|service) + общие настройки
├── modules/           # вся логика: winws, proxy, tgproxy, hosts, dns_jumper, domains, ...
├── ui/                # PySide6-приложение: app.py (мост QWebChannel) + web/ (фронт)
├── lists/             # списки доменов по сервисам (общий слой для всех модулей)
├── strategies/        # стратегии winws2 (*.txt) + assets/ (fake-блобы) + hostlists/
├── tools/             # port_flowseal.py — генератор стратегий из .bat Flowseal
├── upstream/          # сабмодули: zapret2, tg-ws-proxy, zapret-discord-youtube
└── docs/ROADMAP.md    # актуальный статус готового/планируемого
```

## Установка и запуск

```powershell
git clone --recurse-submodules <repo-url>
# если клонировали без сабмодулей:
git submodule update --init

pip install -r requirements.txt
python main.py
```

Приложение само запросит права администратора (UAC) — они нужны для записи в hosts, смены DNS, запуска winws2 и режима TUN у прокси. Режим PAC у прокси и Telegram-прокси работают и без админа.

### Бинарные зависимости (не в репозитории)

- `bin/zapret-win-bundle/` — `winws2.exe` + lua + WinDivert ([bol-van/zapret-win-bundle](https://github.com/bol-van/zapret-win-bundle)). Версию (`COMPAT_VER`) держать в соответствии с сабмодулем `upstream/zapret2`.
- `bin/sing-box/sing-box.exe` — качается кнопкой из UI (вкладка «Прокси»); версия пиннута в `modules/proxy/manager.py`.

## Обновление внешних источников

Сабмодули не форкаются и не правятся — обновление только через git:

```powershell
git submodule update --remote upstream/zapret2
git add upstream/zapret2
git commit -m "bump zapret2"
```

После обновления `upstream/zapret-discord-youtube` стратегии перегенерируются:

```powershell
python tools/port_flowseal.py
```

## Статус

Ранняя стадия, активная разработка. Реализован только UI-режим; TUI и service-режим — заглушки. Подробности — в [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Лицензия

[MIT](LICENSE). Все используемые внешние источники (`upstream/zapret2`, `upstream/tg-ws-proxy`, `upstream/zapret-discord-youtube`) — тоже MIT.
