# Новый фронт (`frontend/`)

Интерфейс на настоящем [shadcn/ui](https://ui.shadcn.com) (база Base UI): Vite, React 19, TypeScript, Tailwind v4, иконки lucide. Все девять страниц перенесены. Исходники — `frontend/`, готовый интерфейс — `ui/web-next/`. Прежний `ui/web/` удалён; старое значение `frontend` в конфиге игнорируется.

Для программы Node не нужен. Он нужен, чтобы собрать и править интерфейс: Node 22+, пакетный менеджер npm.

## Сборка и проверки

```powershell
cd frontend
npm ci              # зависимости строго по package-lock.json
npm run typecheck   # tsc -b
npm test            # каталоги, параметры и множественные числа ru/en
npm run lint        # eslint (код shadcn в src/components/ui и src/hooks не проверяется)
npm run build       # tsc -b + vite build -> ../ui/web-next
```

`ui/web-next/` и `node_modules/` в git не входят. `build.bat` сам выполняет `npm ci` и `npm run build` перед Nuitka (Node 22+ обязателен для всех вариантов) и кладёт в exe готовую `ui/web-next`, но не исходники и не `node_modules`. CI (`ci.yml`) гоняет `typecheck`, `lint`, `test` и `build` до pytest; `release.yml` ставит Node до `build.bat`.

Бандл собирается с `base: "./"`: пути относительные, поэтому страница одинаково открывается с `file://` (PySide6), из pywebview и с локального HTTP-сервера браузерного движка, без правок серверного кода. `qwebchannel.js` лежит в `frontend/public/` и подключается до бандла.

## Каталог интерфейса

`ui/frontend.py` задаёт каталог `ui/web-next/` для всех движков. Если сборки нет, оконный движок сообщает, что нужно выполнить `npm run build` в `frontend/`; браузер показывает страницу с этой подсказкой.

Проверка без окна программы (окно не запускается, браузер headless):

```powershell
python tools/ui_preview.py shot <папка> --frontend next      # обойти страницы нового фронта
python tools/ui_preview.py shot <папка> сценарий.json --frontend next
```

Сценарий — JSON-список шагов (`go`, `click`, `eval`, `shot`, `theme`, `key`, …), см. шапку `tools/ui_shot.mjs`. Для нового фронта селекторы — `data-testid`, например `{"click": "[data-testid=module-toggle-proxy]"}`. Дымовой тест собранной программы: `python tools/smoke_build.py build\Chimera --frontend next`.

## Структура `frontend/src`

| Путь | Что там |
|---|---|
| `main.tsx` | старт: мост, снимок хаба, `app_info`, затем первая отрисовка |
| `App.tsx` | каркас: сайдбар, область страницы, тосты, диалоги |
| `lib/bridge.ts` | мост к Python: Qt WebChannel, pywebview, HTTP с long-poll; `api("метод", …)`, `onPush` |
| `lib/store.ts` | стор состояния модулей, который пушит хаб (`ui/hub.py`); `useStore(ключ)`, `optimistic()` |
| `lib/router.ts` | роутер страниц по хешу и `localStorage` (`chimera.page`) |
| `lib/theme.ts` | полная палитра до React, живые изменения через `appearance_*`, системный режим через `prefers-color-scheme`, слежение за акцентом Windows |
| `lib/i18n.ts`, `lib/language.ts`, `locales/ru.json`, `locales/en.json` | `t("ключ", {…})` и каталог строк |
| `lib/dialogs.ts`, `lib/notify.ts` | `confirmDialog()`, `promptDialog()`, тосты — вызываются откуда угодно |
| `lib/status.ts` | «включён ли модуль», общий для обзора и меню |
| `lib/agent-hooks.ts` | `window.api`, `window.Pages`, `window.Bridge` для внешних проверок |
| `components/ui/` | компоненты shadcn (добавляются `npx shadcn@latest add …`) |
| `components/app/` | сборные части приложения: сайдбар, обёртка страницы, лог, диалоги |
| `pages/` | по файлу на страницу; `registry.ts` — список страниц и меню |

## Правила

- Компоненты — из shadcn, композиция и цвета по правилам shadcn: семантические токены (`bg-primary`, `text-muted-foreground`, а для состояний `text-success`, `text-warning`), `gap-*` вместо `space-y-*`, `data-icon` у иконок в кнопках, формы через `FieldGroup`/`Field`, диалогам всегда заголовок. Перед добавлением компонента — `npx shadcn@latest docs <компонент>`.
- Токены светлой и тёмной темы в `src/index.css` (`:root` и `.dark`). Тему выставляют Python-часть и `initTheme()` перед первой отрисовкой классом `dark` и атрибутом `data-theme` на `<html>` до отрисовки; без них (`npm run dev`) по умолчанию тёмная.
- Вызовы бэкенда — только `api("метод", …)` с литералом имени: по нему `tests/test_cli_parity.py` проверяет, что у каждого действия окна есть команда `chimera`.
- Пользовательские строки — только через `t("ключ", {…})`; в компонентах русского текста нет. Множественные числа: ключи `имя.one`, `имя.few`, `имя.many`, `имя.other` и параметр `count`.
- Состояние модулей не опрашивается: страница читает стор (`useStore`), а тумблеры идут через `optimistic()` (сразу меняет стор, при ошибке откатывает и показывает тост). Ленивые источники хаба включает `useHubWatch(["dns"])`, пока страница открыта.
- Числа с дробной частью — `fmtNum()` (ровно 2 знака или без запятой, округление по третьему знаку).
- Для агентских проверок у значимых элементов есть `data-testid`, у страницы — `data-page` и `data-testid="page-<id>"`. Нативные `<select>` в новом фронте не используются.
- Код в `components/ui/` — это shadcn; правим его только осознанно (например, Ctrl+B по коду клавиши, размытие фона в диалогах убрано).

## Как добавить страницу

1. Файл `src/pages/<имя>.tsx` с компонентом, обёрнутым в `Page`:

   ```tsx
   import { Page } from "@/components/app/page"
   import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
   import { t } from "@/lib/i18n"
   import { useStore } from "@/lib/store"
   import type { DnsState } from "@/lib/types"

   export function DnsPage() {
     const dns = useStore<DnsState>("dns")
     return (
       <Page id="dns" title={t("nav.dns")}>
         <Card>
           <CardHeader><CardTitle>{t("dns.adapters")}</CardTitle></CardHeader>
           <CardContent>…</CardContent>
         </Card>
       </Page>
     )
   }
   ```

2. В `src/pages/registry.ts` добавить компонент. Порядок строк — порядок пунктов меню, `groupKey` — группа, `dot` — от какого модуля горит точка у пункта.
3. Строки — в `src/locales/ru.json` и `en.json` (ключи страницы с общим префиксом: `dns.*`). Форму состояния — в `src/lib/types.ts`.
4. Если странице нужны данные, которых нет в `hub_snapshot`, либо загрузите их вызовом `api(...)` в эффекте страницы, либо заведите источник в хабе (`ui/api.py`, `ui/hub.py`) и включайте его на время показа страницы через `useHubWatch`.
5. `npm run typecheck && npm run build`, затем `python tools/ui_preview.py shot <папка> --frontend next` и посмотреть снимок. `python -m pytest` — тесты паритета с CLI сами найдут новые вызовы `api(...)`.

## Язык и тема

В Настройках доступны русский, английский и язык системы; изменение применяется сразу. `lib/language.ts` запрашивает `lang_get`/`i18n_get`, слушает `langChanged`, объединяет локальный каталог интерфейса с каталогом бэкенда. Множественное число выбирает `Intl.PluralRules`. Ошибки с `code`/`params` переводятся из каталога; исключения сторонних библиотек и системы сохраняют исходный текст (см. [i18n.md](i18n.md)). Тема system/light/dark тоже меняется без перезапуска.

## Оформление: рамки дизайна

Оформление строится из целой согласованной палитры. Сайдбар, фон, карточки,
панели и состояния не красятся по отдельности: такие ключи запрещены схемой
настроек. Это сохраняет иерархию поверхностей и читаемость при смене темы.
Пользователь выбирает палитру, один акцент, скругления и плотность. Собственный
вариант — сохранённое сочетание этих настроек, а не произвольный CSS.

В `config.json` прежний `theme` означает `system/light/dark`. Новые ключи:
`appearance` (`palette`, `accent`, `accent_source`, `radius`, `density`, `name`)
и `appearance_custom` (один сохранённый вариант). Старые конфиги автоматически
получают классическую палитру. Некорректное оформление возвращается к ней.
Запись — через API или CLI, без редактирования работающего конфига вручную.

12 пресетов и ползунок меняют только оттенок. Введённый HEX приводится к HSL:
насыщенность 45–70%, светлота 20–80%; интерфейс сообщает о нормализации.
Из этого значения считаются primary, hover, ring, sidebar-primary, chart-1
и мягкие подложки. Текст на акценте выбирается автоматически между чёрным
и белым. Контраст текста и акцента на поверхностях — минимум 4,5:1; при
нехватке контраста показывается ближайший безопасный вариант и предупреждение.
Исходный нечитаемый цвет не выводится. Акцент Windows проходит те же проверки.

Все вычисления и проверки — в `modules/appearance.py`; новые семантические
цветовые токены не вводятся. Python `ui/theme.py` задаёт полные токены до
отрисовки: Qt на DocumentCreation, WebView2 и HTTP в `<head>`. Нативный фон
берётся из активной палитры и меняется вместе с ней. React использует тот же
расчёт через API. `system` читает режим Windows через Python, без подмены предпочтением Chromium.
Событие `prefers-color-scheme` ускоряет обновление; системный режим и акцент Windows
проверяются также с периодом 1,5 секунды.

Добавление и публикация тем на GitHub, схема каталога, кеш и свободные лицензии —
в [themes/README.md](../themes/README.md). Сторонний каталог содержит только
проверенные значения существующих цветов; CSS, скрипты и ресурсы запрещены.

Проверки: `python -m pytest tests/test_appearance.py`; после сборки фронта —
`python tools/smoke_appearance.py --screenshot appearance.png` (живой интерфейс
с настоящим API, отдельные данные, headless Edge). Этот сценарий запускается в CI.

## Лендинг

Лендинг тоже использует настоящий shadcn/ui: общие компоненты из `frontend/src/components/ui/`,
те же токены, локальные шрифты и lucide. React-страница — `frontend/src/landing/`, входы
на русском и английском — `landing/index.html` и `landing/en/index.html`. Статика —
`landing/public/`. Отдельных зависимостей у сайта нет: используется `frontend/package-lock.json`.

```powershell
cd frontend
npm run dev:landing    # локальный сервер сайта
npm run build:landing  # ../landing/dist, два языка
```

`landing/dist/` не коммитится. Pages workflow собирает сайт перед публикацией. Сайт получает
данные последнего опубликованного релиза через GitHub API; без сети остаются ссылки на Releases.
Новые функции до выпуска помечены как следующее обновление.
