# ZAPRET TUI

Кроссплатформенная TUI-обёртка над [zapret 2](https://github.com/bol-van/zapret2) для обхода DPI-блокировок в России (ТСПУ Роскомнадзора).

## Архитектура

Не форк zapret 2. Используем upstream as-is через git submodule, наши изменения держим строго снаружи:

```
.
├── tui/          # TUI-приложение (стек: TBD — Bubble Tea / Ratatui / Textual / Spectre)
├── strategies/   # Наши Lua-стратегии обхода (грузятся в zapret2 через --lua-file)
├── presets/      # Конфиги пресетов: yt.conf, discord.conf, telegram.conf, ...
├── upstream/
│   └── zapret2/  # git submodule -> github.com/bol-van/zapret2
└── docs/
```

## Обновление zapret 2 из upstream

```bash
git submodule update --remote upstream/zapret2
git add upstream/zapret2
git commit -m "bump zapret2 to <commit-sha>"
```

Сборка/бинарники upstream не модифицируются — мы вызываем `winws2.exe` / `nfqws2` как внешний процесс из нашего TUI.

## Клонирование

```bash
git clone --recurse-submodules <repo-url>
```

Если клонировали без `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

## Статус

Ранняя стадия. Исследование и прототипирование — см. `docs/`.
