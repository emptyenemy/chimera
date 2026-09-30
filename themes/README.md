# Каталог оформления

`catalog.json` — общий каталог встроенных и доступных на GitHub тем. Приложение
проверяет каталог при запуске; «Обновить темы с GitHub» проверяет его вручную.
Источник: `https://raw.githubusercontent.com/emptyenemy/chimera/main/themes/catalog.json`.
После добавления темы в main она появляется без нового выпуска программы.

При ошибке сети используется проверенный кеш `data/themes/catalog.json`, затем
встроенный каталог. Удалённая из GitHub тема остаётся в кеше, чтобы сохранённое
оформление не пропало. Классическая тема всегда берётся из встроенного каталога.
Персональный вариант хранится в настройках: выбранная палитра, один акцент,
режим, скругления и плотность. Цвета отдельных поверхностей не редактируются.

## Добавить тему

1. Скопировать подходящий объект из `catalog.json`, задать уникальный `id`
   (`[a-z][a-z0-9-]*`, до 48 знаков), `name` (до 80), исходный режим `mode`,
   свободную лицензию `license` и HTTPS-ссылку `source` на источник.
2. Задать **оба** согласованных варианта `light` и `dark`: `tokens` и исходный
   `accent`. Цвета — только `#RRGGBB`. Список ключей должен точно совпадать
   с `modules.appearance.COLOR_TOKENS` — существующими 34 семантическими цветами
   `frontend/src/index.css`. Не добавлять новые токены, CSS, ссылки или скрипты.
3. Проверить все пары текста/поверхности: минимум 4,5:1. У тёмного фона
   относительная яркость не выше 0,15, у светлого — не ниже 0,5. Акцент должен
   допускать читаемый вариант в безопасном коридоре HSL.
4. Сохранить лицензию и атрибуцию в `licenses/`, дописать источник ниже.
5. Проверить каталог и все пресеты: `python -m pytest tests/test_appearance.py`.
   Проверить окно: `npm run build` в `frontend/`, затем
   `python tools/smoke_appearance.py`. Опубликовать проверенное изменение в main.

Схема верхнего уровня — `{"schema": 1, "themes": [...]}`, максимум 64 темы,
1 МиБ. Разрешены MIT, MIT/X11, Apache-2.0, BSD-3-Clause, CC0-1.0. Каталог
проверяется целиком; неполное или небезопасное обновление не заменяет кеш.
Цвета primary/ring/sidebar-primary/chart-1 и мягкие подложки из каталога
пересчитываются из единственного акцента при применении.

## Источники и адаптация

| Палитра | Источник | Лицензия |
|---|---|---|
| Dracula | [dracula/dracula-theme](https://github.com/dracula/dracula-theme) | MIT |
| GitHub | [primer/primitives](https://github.com/primer/primitives) | MIT |
| Catppuccin | [catppuccin/catppuccin](https://github.com/catppuccin/catppuccin) | MIT |
| Nord | [nordtheme/nord](https://github.com/nordtheme/nord) | MIT |
| Tokyo Night | [tokyo-night-vscode-theme](https://github.com/tokyo-night/tokyo-night-vscode-theme) | MIT |
| One Dark | [atom/one-dark-ui](https://github.com/atom/one-dark-ui) | MIT |
| Gruvbox | [morhetz/gruvbox](https://github.com/morhetz/gruvbox) | MIT/X11 |
| Solarized | [altercation/solarized](https://github.com/altercation/solarized) | MIT |

Это адаптации палитр к токенам приложения, а не копии редакторских тем.
Для Dracula и One Dark светлый вариант основан на GitHub Light; тёмные варианты
Catppuccin переключаются на Latte. Светлый Catppuccin Latte использует Mocha
как парный тёмный вариант. Цвет текста скорректирован для читаемости интерфейса.
Классическая палитра сохраняет прежнее оформление Chimera.
