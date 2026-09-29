# Новый фронт (`frontend/`)

Интерфейс на настоящем [shadcn/ui](https://ui.shadcn.com) (база Base UI): Vite, React 19, TypeScript, Tailwind v4, иконки lucide. Живёт рядом с прежним (`ui/web/`), пока все страницы не перенесены; какой открыть — ключ `frontend` в `config.json` (`"legacy"` по умолчанию, `"next"`). Статус миграции и порядок страниц — в [ROADMAP.md](ROADMAP.md).

Для программы Node не нужен. Он нужен, чтобы собрать и править интерфейс: Node 22+, пакетный менеджер npm.

## Сборка и проверки

```powershell
cd frontend
npm ci              # зависимости строго по package-lock.json
npm run typecheck   # tsc -b
npm run lint        # eslint (код shadcn в src/components/ui и src/hooks не проверяется)
npm run build       # tsc -b + vite build -> ../ui/web-next
```

`ui/web-next/` и `node_modules/` в git не входят. `build.bat` сам выполняет `npm ci` и `npm run build` перед Nuitka (если есть `frontend/` и node) и кладёт в exe готовую `ui/web-next`, но не исходники и не `node_modules`. CI (`ci.yml`) гоняет `typecheck` и `build` до pytest; `release.yml` ставит Node до `build.bat`.

Бандл собирается с `base: "./"`: пути относительные, поэтому страница одинаково открывается с `file://` (PySide6), из pywebview и с локального HTTP-сервера браузерного движка, без правок серверного кода. `qwebchannel.js` лежит в `frontend/public/` и подключается до бандла.

## Как выбирается фронт

`ui/frontend.py` — единственное место, где движки узнают каталог фронта (`web_dir()`); иконка окна и другие пути от него не зависят. Выбран `"next"`, а сборки нет:

- Qt и pywebview пишут в лог «выполните npm run build в frontend/» и открывают прежний фронт;
- браузерный движок показывает страницу с этим сообщением.

Проверка без окна программы (окно не запускается, браузер headless):

```powershell
python tools/ui_preview.py shot <папка> --frontend next      # обойти страницы нового фронта
python tools/ui_preview.py shot <папка> --frontend all       # оба фронта: <папка>/legacy и <папка>/next
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
| `lib/i18n.ts`, `locales/ru.json` | `t("ключ", {…})` и каталог строк |
| `lib/dialogs.ts`, `lib/notify.ts` | `confirmDialog()`, `promptDialog()`, тосты — вызываются откуда угодно |
| `lib/status.ts` | «включён ли модуль», общий для обзора и меню |
| `lib/agent-hooks.ts` | `window.api`, `window.Pages`, `window.Bridge` для внешних проверок |
| `components/ui/` | компоненты shadcn (добавляются `npx shadcn@latest add …`) |
| `components/app/` | сборные части приложения: сайдбар, обёртка страницы, лог, диалоги |
| `pages/` | по файлу на страницу; `registry.ts` — список страниц и меню |

## Правила

- Компоненты — из shadcn, композиция и цвета по правилам shadcn: семантические токены (`bg-primary`, `text-muted-foreground`, а для состояний `text-success`, `text-warning`), `gap-*` вместо `space-y-*`, `data-icon` у иконок в кнопках, формы через `FieldGroup`/`Field`, диалогам всегда заголовок. Перед добавлением компонента — `npx shadcn@latest docs <компонент>`.
- Токены светлой и тёмной темы в `src/index.css` (`:root` и `.dark`). Тему выставляет Python-часть классом `dark` и атрибутом `data-theme` на `<html>` до отрисовки; без них (`npm run dev`) по умолчанию тёмная.
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

2. В `src/pages/registry.ts` заменить `stub("dns")` на компонент. Порядок строк — порядок пунктов меню, `groupKey` — группа, `dot` — от какого модуля горит точка у пункта.
3. Строки — в `src/locales/ru.json` (ключи страницы с общим префиксом: `dns.*`). Форму состояния — в `src/lib/types.ts`.
4. Если странице нужны данные, которых нет в `hub_snapshot`, либо загрузите их вызовом `api(...)` в эффекте страницы, либо заведите источник в хабе (`ui/api.py`, `ui/hub.py`) и включайте его на время показа страницы через `useHubWatch`.
5. `npm run typecheck && npm run build`, затем `python tools/ui_preview.py shot <папка> --frontend next` и посмотреть снимок. `python -m pytest` — тесты паритета с CLI сами найдут новые вызовы `api(...)`.
