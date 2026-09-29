"""Вкладки TUI. Каждая читает состояние из приложения (app.data) и зовёт действия через app.act.

Состояние приходит от фонового опроса только при изменении: вкладка перерисовывается в
state_changed(). Вкладки, которым нужно тяжёлое (списки, hosts, DNS, логи), объявляют его
в sources() — приложение опрашивает эти источники, только пока вкладка открыта.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, RadioButton, RadioSet, RichLog, Static, Switch

from tui.screens import ListPicker

CHECK, EMPTY = "☑", "☐"


def tag(ok, on="работает", off="остановлен") -> str:
    return f"● {on}" if ok else f"○ {off}"


def fill(table: DataTable, rows: list) -> None:
    """Перезаполняет таблицу, сохраняя выбранную строку и столбец. rows — [(ключ, ячейки…)]."""
    key = col = None
    try:
        coord = table.cursor_coordinate
        key = table.coordinate_to_cell_key(coord).row_key.value
        col = coord.column
    except Exception:  # noqa: BLE001 — пустая таблица: курсора нет
        pass
    table.clear()
    for k, *cells in rows:
        table.add_row(*cells, key=str(k))
    if key is not None:
        try:
            table.move_cursor(row=table.get_row_index(key), column=col or 0, animate=False)
        except Exception:  # noqa: BLE001 — строки больше нет
            pass


def selected_key(table: DataTable) -> str | None:
    try:
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
    except Exception:  # noqa: BLE001
        return None


class Pane(Vertical):
    """Основа вкладки: перерисовка по ключам состояния и объявление ленивых источников."""

    KEYS: tuple = ()
    BINDINGS = [Binding("f", "cycle_focus", "Следующий элемент", show=False)]

    def on_mount(self) -> None:
        self.render_state()

    def state_changed(self, keys) -> None:
        if self.is_mounted and (not self.KEYS or set(keys) & set(self.KEYS)):
            self.render_state()

    def render_state(self) -> None:
        """Перерисовать по app.data(...). Переопределяют вкладки."""

    def sources(self) -> list:
        """Ленивые источники, нужные только пока вкладка открыта: [(ключ, метод, аргументы, период в тиках)]."""
        return []

    def focus_primary(self) -> None:
        """Куда ставить фокус при открытии вкладки."""

    def action_cycle_focus(self) -> None:
        self.screen.focus_next()


# --- обзор -------------------------------------------------------------------------------

MODULES = (("winws", "Обход DPI (winws)"), ("proxy", "Прокси (sing-box)"),
           ("tg", "Telegram-прокси"), ("hosts_state", "Hosts"))


class OverviewPane(Pane):
    KEYS = ("app", "winws", "proxy", "tg", "hosts_state")

    def compose(self) -> ComposeResult:
        yield Static("Подключаюсь к Chimera…", id="ov-app", markup=False, classes="dim")
        for key, title in MODULES:
            with Horizontal(classes="row"):
                yield Static(title, markup=False, classes="name")
                yield Switch(id=f"sw-{key}")
                yield Static("…", id=f"st-{key}", markup=False, classes="state")
        yield Static("", id="ov-notes", markup=False, classes="dim")
        with Horizontal(classes="row"):
            yield Button("Выключить всё", id="panic")

    def focus_primary(self) -> None:
        self.query_one("#sw-winws", Switch).focus()

    def _set(self, key: str, text: str, value: bool) -> None:
        self.query_one(f"#st-{key}", Static).update(text)
        sw = self.query_one(f"#sw-{key}", Switch)
        if sw.value != value:
            with sw.prevent(Switch.Changed):
                sw.value = value

    def render_state(self) -> None:
        app = self.app
        a = app.data("app")
        if a:
            extra = ", служба в фоне" if a.get("service_running") else ""
            adm = "да" if a.get("admin") else "нет"
            self.query_one("#ov-app", Static).update(f"Chimera {a.get('version', '?')} · права администратора: {adm}{extra}")
        notes = []
        w = app.data("winws")
        if w is not None:
            cur = f", стратегия {w['current']}" if w.get("current") else ""
            ext = " (запущен не из Chimera)" if w.get("external") else ""
            self._set("winws", tag(w.get("running")) + cur + ext, bool(w.get("running")))
            if w.get("error"):
                notes.append(f"winws: {w['error']}")
        p = app.data("proxy")
        if p is not None:
            self._set("proxy", tag(p.get("running")) + f", режим {p.get('mode', 'pac')}", bool(p.get("running")))
            if p.get("error"):
                notes.append(f"прокси: {p['error']}")
        t = app.data("tg")
        if t is not None:
            self._set("tg", tag(t.get("running")), bool(t.get("running")))
            if t.get("error"):
                notes.append(f"Telegram: {t['error']}")
        h = app.data("hosts_state")
        if h is not None:
            applied = "применено" if h.get("applied") else "не применено"
            self._set("hosts_state", f"{tag(h.get('enabled'), 'включено', 'выключено')}, {applied}, записей: {h.get('count', 0)}",
                      bool(h.get("enabled")))
        for key, title in MODULES:
            if app.error(key):
                notes.append(f"{title}: {app.error(key)}")
        self.query_one("#ov-notes", Static).update("\n".join(notes))

    def on_switch_changed(self, event: Switch.Changed) -> None:
        event.stop()
        key, want, app = event.switch.id[3:], event.value, self.app
        if key == "winws":
            if want:
                sid = (app.data("winws") or {}).get("last_strategy")
                if not sid:
                    app.status("Стратегия не выбрана: откройте вкладку «Стратегии» и нажмите Enter на нужной.", error=True)
                    app.resync()
                    return
                app.act(f"Запуск стратегии {sid}", "winws_start", sid, journal=f"winws start {sid}")
            else:
                app.act("Остановка обхода", "winws_stop", journal="winws stop")
        elif key == "proxy":
            app.act("Запуск прокси" if want else "Остановка прокси", "proxy_start" if want else "proxy_stop",
                    journal="proxy start" if want else "proxy stop")
        elif key == "tg":
            app.act("Запуск Telegram-прокси" if want else "Остановка Telegram-прокси",
                    "tg_start" if want else "tg_stop", journal="tg start" if want else "tg stop")
        elif key == "hosts_state":
            app.act("Включение hosts" if want else "Выключение hosts", "hosts_set_enabled", want,
                    journal="hosts on" if want else "hosts off")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "panic":
            event.stop()
            self.app.confirm("Выключить всё: обход, прокси, Telegram-прокси, службу, hosts, и вернуть DNS, "
                             "который ставила Chimera?", self._panic)

    def _panic(self) -> None:
        def after(data):
            failed = [f"{s['step']} ({s.get('error')})" for s in (data or {}).get("steps", []) if not s.get("ok")]
            if failed:
                self.app.status("Выключить всё: не удалось: " + "; ".join(failed), error=True)

        self.app.act("Выключить всё", "panic_all", journal="panic", after=after)


# --- стратегии -----------------------------------------------------------------------------------

class StrategiesPane(Pane):
    KEYS = ("winws",)
    BINDINGS = [*Pane.BINDINGS, Binding("slash", "search", "Поиск", show=False), Binding("x", "stop", "Остановить обход")]

    def compose(self) -> ComposeResult:
        yield Static("…", id="st-head", markup=False)
        yield Input(placeholder="Поиск по стратегиям (/)", id="st-search")
        yield DataTable(id="st-table", cursor_type="row", zebra_stripes=True)
        yield Static("Enter — запустить выбранную стратегию · x — остановить · / — поиск", markup=False, classes="dim")

    def on_mount(self) -> None:
        t = self.query_one("#st-table", DataTable)
        t.add_column("", key="mark", width=2)
        t.add_column("Стратегия", key="id")
        t.add_column("Описание", key="desc")
        super().on_mount()

    def focus_primary(self) -> None:
        self.query_one("#st-table", DataTable).focus()

    def action_search(self) -> None:
        self.query_one("#st-search", Input).focus()

    def action_stop(self) -> None:
        self.app.act("Остановка обхода", "winws_stop", journal="winws stop")

    def render_state(self) -> None:
        w = self.app.data("winws")
        if w is None:
            self.query_one("#st-head", Static).update("Нет данных о winws.")
            return
        head = tag(w.get("running"))
        if w.get("current"):
            head += f", стратегия {w['current']}"
        if w.get("last_strategy") and not w.get("running"):
            head += f", последняя: {w['last_strategy']}"
        if w.get("version"):
            head += f" · версия {w['version']}"
        if w.get("error"):
            head += f" · ошибка: {w['error']}"
        self.query_one("#st-head", Static).update(head)
        q = self.query_one("#st-search", Input).value.strip().lower()
        rows = []
        for s in w.get("strategies") or []:
            sid, name, desc = s.get("id", ""), s.get("name", ""), s.get("desc") or ""
            if q and q not in sid.lower() and q not in name.lower() and q not in desc.lower():
                continue
            mark = "●" if w.get("running") and w.get("current") == sid else ("·" if w.get("last_strategy") == sid else "")
            rows.append((sid, mark, sid, desc or name))
        fill(self.query_one("#st-table", DataTable), rows)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.render_state()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.query_one("#st-table", DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        sid = event.row_key.value
        self.app.act(f"Запуск стратегии {sid}", "winws_start", sid, journal=f"winws start {sid}")


# --- списки -------------------------------------------------------------------------------------------

class ListsPane(Pane):
    KEYS = ("lists",)
    BINDINGS = [*Pane.BINDINGS, Binding("e", "edit", "Править"), Binding("space", "toggle", "Отметить")]
    COLUMNS = ("winws", "proxy", "hosts")

    def compose(self) -> ComposeResult:
        yield Static("Пробел/Enter на «winws» или «прокси» — включить список в транспорт · e — править файл", markup=False, classes="dim")
        yield DataTable(id="ls-table", cursor_type="cell", zebra_stripes=True)
        yield Static("", id="ls-note", markup=False, classes="dim")

    def on_mount(self) -> None:
        t = self.query_one("#ls-table", DataTable)
        t.add_column("Список", key="name")
        t.add_column("Доменов", key="count")
        t.add_column("в winws", key="winws")
        t.add_column("в прокси", key="proxy")
        t.add_column("в hosts", key="hosts")
        super().on_mount()

    def sources(self) -> list:
        return [("lists", "lists_all", (), 3)]

    def focus_primary(self) -> None:
        self.query_one("#ls-table", DataTable).focus()

    def render_state(self) -> None:
        items = self.app.data("lists") or []
        rows = [(i["name"], i["name"], i.get("count", 0), *(CHECK if i.get(c) else EMPTY for c in self.COLUMNS)) for i in items]
        fill(self.query_one("#ls-table", DataTable), rows)
        if self.app.error("lists"):
            self.query_one("#ls-note", Static).update(f"Не удалось получить списки: {self.app.error('lists')}")

    def _cell(self):
        t = self.query_one("#ls-table", DataTable)
        try:
            coord = t.cursor_coordinate
            return t.coordinate_to_cell_key(coord).row_key.value, coord.column
        except Exception:  # noqa: BLE001
            return None, None

    def _toggle(self, name: str, column: int) -> None:
        app, items = self.app, self.app.data("lists") or []
        if column == 4:
            app.status("Привязка списков к провайдерам hosts — на вкладке Hosts.")
            return
        if column not in (2, 3):
            return
        flag, method, title = ("winws", "winws_set_lists", "Списки обхода") if column == 2 else ("proxy", "proxy_set_lists", "Списки прокси")
        names = [i["name"] for i in items if i.get(flag)]
        names = [n for n in names if n != name] if name in names else [*names, name]
        app.act(f"{title}: {name}", method, names, journal=f"{'winws' if column == 2 else 'proxy'} lists {' '.join(names)}")

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        event.stop()
        self._toggle(event.cell_key.row_key.value, event.coordinate.column)

    def action_toggle(self) -> None:
        name, col = self._cell()
        if name is not None:
            self._toggle(name, col)

    def action_edit(self) -> None:
        name, _ = self._cell()
        if name is not None:
            self.app.edit_list(name)


# --- прокси -----------------------------------------------------------------------------------------------

MODES = (("pac", "PAC (без прав администратора)"), ("split", "Выборочный TUN (приложения)"), ("tun", "TUN (весь трафик)"))


class ProxyPane(Pane):
    KEYS = ("proxy",)
    BINDINGS = [*Pane.BINDINGS, Binding("delete", "remove_app", "Убрать приложение")]

    def compose(self) -> ComposeResult:
        yield Static("…", id="px-head", markup=False)
        with Horizontal(classes="row"):
            yield Button("Запустить", id="px-toggle")
        yield Static("Режим", markup=False, classes="dim")
        with RadioSet(id="px-mode"):
            for mode, title in MODES:
                yield RadioButton(title, id=f"mode-{mode}")
        yield Static("Приложения для выборочного TUN (Delete — убрать)", markup=False, classes="dim")
        yield DataTable(id="px-apps", cursor_type="row")
        yield Input(placeholder="Добавить приложение, например Discord.exe", id="px-add")

    def on_mount(self) -> None:
        self.query_one("#px-apps", DataTable).add_column("Образ", key="app")
        super().on_mount()

    def focus_primary(self) -> None:
        self.query_one("#px-toggle", Button).focus()

    def render_state(self) -> None:
        p = self.app.data("proxy")
        if p is None:
            self.query_one("#px-head", Static).update("Нет данных о прокси.")
            return
        head = f"{tag(p.get('running'))}, режим {p.get('mode', 'pac')}"
        if p.get("external"):
            head += " (запущен не из Chimera)"
        core = p.get("core") or {}
        head += " · ядро sing-box: " + (core.get("version") or "есть" if core.get("present") else "не скачано")
        head += f" · доменов {p.get('domains', 0)}, подсетей {p.get('ips', 0)}"
        if p.get("parsed"):
            head += f" · {p['parsed'].get('protocol')} → {p['parsed'].get('server')}"
        if p.get("error"):
            head += f" · ошибка: {p['error']}"
        self.query_one("#px-head", Static).update(head)
        self.query_one("#px-toggle", Button).label = "Остановить" if p.get("running") else "Запустить"
        mode = p.get("mode", "pac")
        btn = self.query_one(f"#mode-{mode}", RadioButton) if mode in dict(MODES) else None
        if btn is not None and not btn.value:
            btn.value = True
        fill(self.query_one("#px-apps", DataTable), [(a, a) for a in p.get("apps") or []])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "px-toggle":
            return
        event.stop()
        if (self.app.data("proxy") or {}).get("running"):
            self.app.act("Остановка прокси", "proxy_stop", journal="proxy stop")
        else:
            self.app.act("Запуск прокси", "proxy_start", journal="proxy start")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        mode = (event.pressed.id or "")[5:]
        if mode and mode != (self.app.data("proxy") or {}).get("mode", "pac"):
            self.app.act(f"Режим прокси: {mode}", "proxy_set_mode", mode, journal=f"proxy mode {mode}")

    def _apps(self) -> list:
        return list((self.app.data("proxy") or {}).get("apps") or [])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        name = event.value.strip()
        if not name:
            return
        event.input.value = ""
        apps = self._apps()
        if name.lower() not in (a.lower() for a in apps):
            self.app.act(f"Приложение {name}", "proxy_set_apps", [*apps, name], journal=f"proxy apps +{name}")

    def action_remove_app(self) -> None:
        name = selected_key(self.query_one("#px-apps", DataTable))
        if name:
            self.app.act(f"Убрать {name}", "proxy_set_apps", [a for a in self._apps() if a != name], journal=f"proxy apps -{name}")


# --- hosts -----------------------------------------------------------------------------------------------------

class HostsPane(Pane):
    KEYS = ("hosts", "hosts_state")

    def compose(self) -> ComposeResult:
        yield Static("…", id="hs-head", markup=False)
        with Horizontal(classes="row"):
            yield Static("Подмена hosts", markup=False, classes="name")
            yield Switch(id="hs-enabled")
        yield Static("Провайдеры и привязанные к ним списки (Enter — выбрать списки)", markup=False, classes="dim")
        yield DataTable(id="hs-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one("#hs-table", DataTable)
        t.add_column("Провайдер", key="name")
        t.add_column("Тип", key="type")
        t.add_column("Списки", key="lists")
        super().on_mount()

    def sources(self) -> list:
        return [("hosts", "hosts_overview", (), 3)]

    def focus_primary(self) -> None:
        self.query_one("#hs-table", DataTable).focus()

    def _assignments(self) -> dict:
        return dict((self.app.data("hosts_state") or {}).get("assignments") or {})

    def render_state(self) -> None:
        st = self.app.data("hosts_state")
        if st is not None:
            applied = "применено" if st.get("applied") else "не применено"
            self.query_one("#hs-head", Static).update(
                f"{tag(st.get('enabled'), 'включено', 'выключено')}, {applied}, записей: {st.get('count', 0)}")
            sw = self.query_one("#hs-enabled", Switch)
            if sw.value != bool(st.get("enabled")):
                with sw.prevent(Switch.Changed):
                    sw.value = bool(st.get("enabled"))
        ov = self.app.data("hosts") or {}
        assigned = self._assignments()
        rows = [(p["id"], p.get("name") or p["id"], p.get("type", ""), ", ".join(assigned.get(p["id"]) or []) or "—")
                for p in ov.get("providers") or []]
        fill(self.query_one("#hs-table", DataTable), rows)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        event.stop()
        want = event.value
        if want != bool((self.app.data("hosts_state") or {}).get("enabled")):
            self.app.act("Включение hosts" if want else "Выключение hosts", "hosts_set_enabled", want,
                         journal="hosts on" if want else "hosts off")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        pid = event.row_key.value
        names = [i["name"] for i in (self.app.data("hosts") or {}).get("lists") or []]

        def chosen(result):
            if result is None:
                return
            mapping = {**self._assignments(), pid: result}
            self.app.act(f"Списки провайдера {pid}", "hosts_set_assignments", {k: v for k, v in mapping.items() if v},
                         journal=f"hosts assign {pid}={','.join(result)}")

        self.app.push_screen(ListPicker(f"Списки для провайдера {pid}", names, self._assignments().get(pid) or []), chosen)


# --- DNS -----------------------------------------------------------------------------------------------------------

TRIAL_SECONDS = 15


class DnsPane(Pane):
    KEYS = ("dns",)
    BINDINGS = [*Pane.BINDINGS, Binding("r", "reset", "Сбросить на DHCP")]

    def compose(self) -> ComposeResult:
        yield Static("", id="dn-trial", markup=False)
        with Horizontal(id="dn-buttons", classes="row hidden"):
            yield Button("Оставить", id="dn-keep")
            yield Button("Вернуть сейчас", id="dn-revert")
        yield Static("Адаптеры (r — сбросить выбранный на DHCP)", markup=False, classes="dim")
        yield DataTable(id="dn-adapters", cursor_type="row")
        yield Static(f"Провайдеры (Enter — применить к выбранному адаптеру с откатом через {TRIAL_SECONDS} с)", markup=False, classes="dim")
        yield DataTable(id="dn-providers", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        a = self.query_one("#dn-adapters", DataTable)
        a.add_column("№", key="i", width=4)
        a.add_column("Адаптер", key="name")
        a.add_column("Состояние", key="status")
        a.add_column("DNS", key="dns")
        p = self.query_one("#dn-providers", DataTable)
        p.add_column("Провайдер", key="name")
        p.add_column("Серверы", key="servers")
        super().on_mount()

    def sources(self) -> list:
        trials = (self.app.data("dns") or {}).get("trials")
        return [("dns", "dns_state", (), 1 if trials else 5)]

    def focus_primary(self) -> None:
        self.query_one("#dn-adapters", DataTable).focus()

    def render_state(self) -> None:
        d = self.app.data("dns") or {}
        fill(self.query_one("#dn-adapters", DataTable),
             [(a["index"], a["index"], a.get("name", ""), a.get("status", ""), ", ".join(a.get("dns") or []) or "—")
              for a in d.get("adapters") or []])
        fill(self.query_one("#dn-providers", DataTable),
             [(p["id"], p.get("name") or p["id"], ", ".join(p.get("servers") or [])) for p in d.get("providers") or []])
        trials = d.get("trials") or []
        self.query_one("#dn-buttons").set_class(not trials, "hidden")
        self.query_one("#dn-trial", Static).update(
            "\n".join(f"Проба DNS на адаптере {t.get('adapter')}: {t.get('provider')}, до отката {t.get('seconds_left')} с — "
                      "оставьте или верните" for t in trials))
        if self.app.error("dns"):
            self.query_one("#dn-trial", Static).update(f"Не удалось получить DNS: {self.app.error('dns')}")

    def _adapter(self):
        key = selected_key(self.query_one("#dn-adapters", DataTable))
        return int(key) if key is not None else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if event.data_table.id != "dn-providers":
            return
        adapter, pid = self._adapter(), event.row_key.value
        if adapter is None:
            self.app.status("Сначала выберите адаптер в верхней таблице.", error=True)
            return
        self.app.confirm(f"Поставить DNS «{pid}» на адаптер {adapter}? Если не подтвердить за {TRIAL_SECONDS} с, вернётся прежний.",
                         lambda: self.app.act(f"DNS {pid} на адаптере {adapter}", "dns_set_trial", adapter, pid, TRIAL_SECONDS,
                                              journal=f"dns trial {adapter} {pid}"))

    def action_reset(self) -> None:
        adapter = self._adapter()
        if adapter is None:
            return
        self.app.confirm(f"Вернуть DNS адаптера {adapter} на автоматический (DHCP)?",
                         lambda: self.app.act(f"Сброс DNS адаптера {adapter}", "dns_reset", adapter, journal=f"dns reset {adapter}"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dn-keep":
            event.stop()
            self.app.act("DNS оставлен", "dns_trial_confirm", journal="dns trial-confirm")
        elif event.button.id == "dn-revert":
            event.stop()
            self.app.act("DNS возвращён", "dns_trial_revert", journal="dns trial-revert")


# --- Telegram-прокси ---------------------------------------------------------------------------------------------------------

class TgPane(Pane):
    KEYS = ("tg", "tg_stats")

    def compose(self) -> ComposeResult:
        yield Static("…", id="tg-head", markup=False)
        with Horizontal(classes="row"):
            yield Button("Запустить", id="tg-toggle")
        yield Static("", id="tg-info", markup=False)
        yield Static("", id="tg-stats", markup=False, classes="dim")

    def sources(self) -> list:
        if (self.app.data("tg") or {}).get("running"):
            return [("tg_stats", "tg_stats", (), 2)]
        return []

    def focus_primary(self) -> None:
        self.query_one("#tg-toggle", Button).focus()

    @staticmethod
    def masked_link(t: dict) -> str:
        """Ссылка без секрета: секрет в TUI не показывается никогда (полная — `chimera tg link --show-secrets`)."""
        if not t.get("link"):
            return "—"
        return f"tg://proxy?server={t.get('host')}&port={t.get('port')}&secret=…(скрыто)"

    def render_state(self) -> None:
        t = self.app.data("tg")
        if t is None:
            self.query_one("#tg-head", Static).update("Нет данных о Telegram-прокси.")
            return
        head = tag(t.get("running"))
        if t.get("version"):
            head += f" · ядро {t['version']}"
        if t.get("error"):
            head += f" · ошибка: {t['error']}"
        self.query_one("#tg-head", Static).update(head)
        self.query_one("#tg-toggle", Button).label = "Остановить" if t.get("running") else "Запустить"
        self.query_one("#tg-info", Static).update(
            f"Адрес: {t.get('host')}:{t.get('port')} · автозапуск: {'да' if t.get('autostart') else 'нет'}\n"
            f"Ссылка: {self.masked_link(t)}\nПолная ссылка: chimera tg link --show-secrets")
        stats = self.app.data("tg_stats")
        if stats and t.get("running"):
            from modules.cli.commands import render
            self.query_one("#tg-stats", Static).update("\n".join(render(stats)))
        else:
            self.query_one("#tg-stats", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "tg-toggle":
            return
        event.stop()
        if (self.app.data("tg") or {}).get("running"):
            self.app.act("Остановка Telegram-прокси", "tg_stop", journal="tg stop")
        else:
            self.app.act("Запуск Telegram-прокси", "tg_start", journal="tg start")


# --- логи ---------------------------------------------------------------------------------------------------------------------------

LOG_FILES = (("winws", "winws.log", "winws_log"), ("proxy", "proxy.log", "proxy_log"), ("tg", "tgproxy.log", "tg_log"))
LOG_LINES = 1000


class LogsPane(Pane):
    def __init__(self):
        super().__init__()
        self.log_module = "winws"
        self.log_offset = 0

    def compose(self) -> ComposeResult:
        with RadioSet(id="lg-file"):
            for mod, name, _m in LOG_FILES:
                yield RadioButton(name, id=f"log-{mod}", value=mod == "winws")
        yield RichLog(id="lg-view", max_lines=LOG_LINES, wrap=True, markup=False, highlight=False)

    def _key(self) -> str:
        return f"log:{self.log_module}"

    def sources(self) -> list:
        method = next(m for mod, _n, m in LOG_FILES if mod == self.log_module)
        return [(self._key(), method, (self.log_offset,), 1)]

    def focus_primary(self) -> None:
        self.query_one("#lg-file", RadioSet).focus()

    def state_changed(self, keys) -> None:
        if not self.is_mounted or self._key() not in keys:
            return
        d = self.app.data(self._key())
        if not d:
            return
        view = self.query_one("#lg-view", RichLog)
        if d.get("reset"):
            view.clear()
        for line in (d.get("data") or "").splitlines():
            view.write(line)
        self.log_offset = d.get("offset", self.log_offset)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        mod = (event.pressed.id or "")[4:]
        if mod and mod != self.log_module:
            self.log_module, self.log_offset = mod, 0
            self.query_one("#lg-view", RichLog).clear()
            self.app.forget(self._key())
            self.app.refresh_now(force=True)


# --- настройки -----------------------------------------------------------------------------------------------------------------------------

THEMES = (("system", "Как в системе"), ("light", "Светлая"), ("dark", "Тёмная"))


class SettingsPane(Pane):
    KEYS = ("config", "app")

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("", id="se-info", markup=False)
            yield Static("Тема окна Chimera", markup=False, classes="dim")
            with RadioSet(id="se-theme"):
                for value, title in THEMES:
                    yield RadioButton(title, id=f"theme-{value}")
            yield Static("", id="se-lang", markup=False)

    def sources(self) -> list:
        return [("config", "config_read", (), 5)]

    def focus_primary(self) -> None:
        self.query_one("#se-theme", RadioSet).focus()

    def render_state(self) -> None:
        a, cfg = self.app.data("app") or {}, self.app.data("config") or {}
        self.query_one("#se-info", Static).update(
            f"Версия Chimera: {a.get('version', '?')}\nПрава администратора: {'да' if a.get('admin') else 'нет'}\n"
            f"Режим интерфейса: {cfg.get('interface', '?')}")
        theme = cfg.get("theme", "system")
        btn = self.query_one(f"#theme-{theme}", RadioButton) if theme in dict(THEMES) else None
        if btn is not None and not btn.value:
            btn.value = True
        lang = self.query_one("#se-lang", Static)
        lang.update(f"Язык: {cfg['language']}" if "language" in cfg else "")
        lang.set_class("language" not in cfg, "hidden")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        theme = (event.pressed.id or "")[6:]
        if theme and theme != (self.app.data("config") or {}).get("theme", "system"):
            self.app.act(f"Тема окна: {theme}", "config_set", "theme", theme, journal=f"config set theme {theme}")

