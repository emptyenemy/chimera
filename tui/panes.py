"""Разделы TUI. Каждая читает состояние из приложения (app.data) и зовёт действия через app.act.

Состояние приходит от фонового опроса только при изменении: раздел перерисовывается в
state_changed(). Вкладки, которым нужно тяжёлое (списки, hosts, DNS, логи), объявляют его
в sources() — приложение опрашивает эти источники, только пока раздел открыта.
"""

from modules.i18n import t as _tr

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, RadioButton, RadioSet, RichLog, Static, Switch

from tui.screens import ListPicker

CHECK, EMPTY = "☑", "☐"


def tag(ok, on=None, off=None) -> str:
    on = on if on is not None else _tr('tui.panes.running')
    off = off if off is not None else _tr('tui.panes.stopped')
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
    """Основа разделы: перерисовка по ключам состояния и объявление ленивых источников."""

    KEYS: tuple = ()
    BINDINGS = [Binding("f", "cycle_focus", _tr('tui.panes.next_element'), show=False)]

    def on_mount(self) -> None:
        self.render_state()

    def state_changed(self, keys) -> None:
        if self.is_mounted and (not self.KEYS or set(keys) & set(self.KEYS)):
            self.render_state()

    def render_state(self) -> None:
        """Перерисовать по app.data(...). Переопределяют разделы."""

    def sources(self) -> list:
        """Ленивые источники, нужные только пока раздел открыта: [(ключ, метод, аргументы, период в тиках)]."""
        return []

    def focus_primary(self) -> None:
        """Куда ставить фокус при открытии разделы."""

    def action_cycle_focus(self) -> None:
        self.screen.focus_next()


# --- обзор -------------------------------------------------------------------------------

MODULES = (("winws", _tr('tui.panes.dpi_bypass_winws')), ("proxy", _tr('tui.panes.proxy_sing_box')),
           ("tg", _tr('tui.panes.telegram_proxy')), ("hosts_state", "Hosts"))


class OverviewPane(Pane):
    KEYS = ("app", "winws", "proxy", "tg", "hosts_state")

    def compose(self) -> ComposeResult:
        yield Static(_tr('tui.panes.connecting_to_chimera'), id="ov-app", markup=False, classes="dim")
        for key, title in MODULES:
            with Horizontal(classes="row"):
                yield Static(title, markup=False, classes="name")
                yield Switch(id=f"sw-{key}")
                yield Static("…", id=f"st-{key}", markup=False, classes="state")
        yield Static("", id="ov-notes", markup=False, classes="dim")
        with Horizontal(classes="row"):
            yield Button(_tr('tui.panes.turn_everything_off'), id="panic")

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
            extra = _tr('tui.panes.background_service') if a.get("service_running") else ""
            adm = _tr('tui.panes.yes') if a.get("admin") else _tr('tui.panes.no')
            self.query_one("#ov-app", Static).update(_tr('tui.panes.chimera_administrator_rights', p0=a.get('version', '?'), p1=adm, p2=extra))
        notes = []
        w = app.data("winws")
        if w is not None:
            cur = _tr('tui.panes.strategy_228', p0=w['current']) if w.get("current") else ""
            ext = _tr('tui.panes.started_outside_chimera') if w.get("external") else ""
            self._set("winws", tag(w.get("running")) + cur + ext, bool(w.get("running")))
            if w.get("error"):
                notes.append(f"winws: {w['error']}")
        p = app.data("proxy")
        if p is not None:
            self._set("proxy", tag(p.get("running")) + _tr('tui.panes.mode_267', p0=p.get('mode', 'pac')), bool(p.get("running")))
            if p.get("error"):
                notes.append(_tr('tui.panes.proxy', p0=p['error']))
        t = app.data("tg")
        if t is not None:
            self._set("tg", tag(t.get("running")), bool(t.get("running")))
            if t.get("error"):
                notes.append(f"Telegram: {t['error']}")
        h = app.data("hosts_state")
        if h is not None:
            applied = _tr('tui.panes.applied') if h.get("applied") else _tr('tui.panes.not_applied')
            self._set("hosts_state", _tr('tui.panes.entries',
                p0=tag(h.get('enabled'), _tr('tui.panes.enabled'), _tr('tui.panes.disabled')),
                p1=applied,
                p2=h.get('count', 0),
            ),
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
                    app.status(_tr('tui.panes.no_strategy_selected_open_strategies_and_press_e'), error=True)
                    app.resync()
                    return
                app.act(_tr('tui.panes.starting_strategy', p0=sid), "winws_start", sid, journal=f"winws start {sid}")
            else:
                app.act(_tr('tui.panes.stopping_bypass'), "winws_stop", journal="winws stop")
        elif key == "proxy":
            app.act(_tr('tui.panes.starting_proxy') if want else _tr('tui.panes.stopping_proxy'), "proxy_start" if want else "proxy_stop",
                    journal="proxy start" if want else "proxy stop")
        elif key == "tg":
            app.act(_tr('tui.panes.starting_telegram_proxy') if want else _tr('tui.panes.stopping_telegram_proxy'),
                    "tg_start" if want else "tg_stop", journal="tg start" if want else "tg stop")
        elif key == "hosts_state":
            app.act(_tr('tui.panes.enabling_hosts') if want else _tr('tui.panes.disabling_hosts'), "hosts_set_enabled", want,
                    journal="hosts on" if want else "hosts off")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "panic":
            event.stop()
            self.app.confirm(_tr('tui.panes.turn_off_bypass_proxy_telegram_proxy_service_and'), self._panic)

    def _panic(self) -> None:
        def after(data):
            failed = [f"{s['step']} ({s.get('error')})" for s in (data or {}).get("steps", []) if not s.get("ok")]
            if failed:
                self.app.status(_tr('tui.panes.turn_everything_off_failed') + "; ".join(failed), error=True)

        self.app.act(_tr('tui.panes.turn_everything_off'), "panic_all", journal="panic", after=after)


# --- стратегии -----------------------------------------------------------------------------------

class StrategiesPane(Pane):
    KEYS = ("winws",)
    BINDINGS = [*Pane.BINDINGS, Binding("slash", "search", _tr('tui.panes.search'), show=False), Binding("x", "stop", _tr('tui.panes.stop_bypass'))]

    def compose(self) -> ComposeResult:
        yield Static("…", id="st-head", markup=False)
        yield Input(placeholder=_tr('tui.panes.search_strategies'), id="st-search")
        yield DataTable(id="st-table", cursor_type="row", zebra_stripes=True)
        yield Static(_tr('tui.panes.enter_to_start_the_selected_strategy_x_to_stop_t'), markup=False, classes="dim")

    def on_mount(self) -> None:
        t = self.query_one("#st-table", DataTable)
        t.add_column("", key="mark", width=2)
        t.add_column(_tr('tui.panes.strategy'), key="id")
        t.add_column(_tr('tui.panes.description'), key="desc")
        super().on_mount()

    def focus_primary(self) -> None:
        self.query_one("#st-table", DataTable).focus()

    def action_search(self) -> None:
        self.query_one("#st-search", Input).focus()

    def action_stop(self) -> None:
        self.app.act(_tr('tui.panes.stopping_bypass'), "winws_stop", journal="winws stop")

    def render_state(self) -> None:
        w = self.app.data("winws")
        if w is None:
            self.query_one("#st-head", Static).update(_tr('tui.panes.no_winws_data'))
            return
        head = tag(w.get("running"))
        if w.get("current"):
            head += _tr('tui.panes.strategy_188', p0=w['current'])
        if w.get("last_strategy") and not w.get("running"):
            head += _tr('tui.panes.last', p0=w['last_strategy'])
        if w.get("version"):
            head += _tr('tui.panes.version', p0=w['version'])
        if w.get("error"):
            head += _tr('tui.panes.error', p0=w['error'])
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
        self.app.act(_tr('tui.panes.starting_strategy', p0=sid), "winws_start", sid, journal=f"winws start {sid}")


# --- списки -------------------------------------------------------------------------------------------

class ListsPane(Pane):
    KEYS = ("lists",)
    BINDINGS = [*Pane.BINDINGS, Binding("e", "edit", _tr('tui.panes.edit')), Binding("space", "toggle", _tr('tui.panes.select'))]
    COLUMNS = ("winws", "proxy", "hosts")

    def compose(self) -> ComposeResult:
        yield Static(_tr('tui.panes.space_enter_on_winws_or_proxy_to_assign_a_list_e'), markup=False, classes="dim")
        yield DataTable(id="ls-table", cursor_type="cell", zebra_stripes=True)
        yield Static("", id="ls-note", markup=False, classes="dim")

    def on_mount(self) -> None:
        t = self.query_one("#ls-table", DataTable)
        t.add_column(_tr('tui.panes.list'), key="name")
        t.add_column(_tr('tui.panes.domains'), key="count")
        t.add_column(_tr('tui.panes.in_winws'), key="winws")
        t.add_column(_tr('tui.panes.in_proxy'), key="proxy")
        t.add_column(_tr('tui.panes.in_hosts'), key="hosts")
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
            self.query_one("#ls-note", Static).update(_tr('tui.panes.could_not_load_lists', p0=self.app.error('lists')))

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
            app.status(_tr('tui.panes.assign_lists_to_hosts_providers_on_the_hosts_tab'))
            return
        if column not in (2, 3):
            return
        flag, method, title = ("winws", "winws_set_lists", _tr('tui.panes.bypass_lists')) if column == 2 else (
            "proxy", "proxy_set_lists", _tr('tui.panes.proxy_lists'))
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

MODES = (("pac", _tr('tui.panes.pac_no_administrator_rights')), ("split", _tr('tui.panes.selective_tun_applications')),
         ("tun", _tr('tui.panes.tun_all_traffic')))


class ProxyPane(Pane):
    KEYS = ("proxy",)
    BINDINGS = [*Pane.BINDINGS, Binding("delete", "remove_app", _tr('tui.panes.remove_application'))]

    def compose(self) -> ComposeResult:
        yield Static("…", id="px-head", markup=False)
        with Horizontal(classes="row"):
            yield Button(_tr('tui.panes.start'), id="px-toggle")
        yield Static(_tr('tui.panes.mode_241'), markup=False, classes="dim")
        with RadioSet(id="px-mode"):
            for mode, title in MODES:
                yield RadioButton(title, id=f"mode-{mode}")
        yield Static(_tr('tui.panes.applications_for_selective_tun_delete_to_remove'), markup=False, classes="dim")
        yield DataTable(id="px-apps", cursor_type="row")
        yield Input(placeholder=_tr('tui.panes.add_an_application_e_g_discord_exe'), id="px-add")

    def on_mount(self) -> None:
        self.query_one("#px-apps", DataTable).add_column(_tr('tui.panes.image'), key="app")
        super().on_mount()

    def focus_primary(self) -> None:
        self.query_one("#px-toggle", Button).focus()

    def render_state(self) -> None:
        p = self.app.data("proxy")
        if p is None:
            self.query_one("#px-head", Static).update(_tr('tui.panes.no_proxy_data'))
            return
        head = _tr('tui.panes.mode', p0=tag(p.get('running')), p1=p.get('mode', 'pac'))
        if p.get("external"):
            head += _tr('tui.panes.started_outside_chimera')
        core = p.get("core") or {}
        head += _tr('tui.panes.sing_box_core') + (core.get("version") or _tr('tui.panes.present') if core.get("present") else _tr('tui.panes.not_downloaded'))
        head += _tr('tui.panes.domains_subnets', p0=p.get('domains', 0), p1=p.get('ips', 0))
        if p.get("parsed"):
            head += f" · {p['parsed'].get('protocol')} → {p['parsed'].get('server')}"
        if p.get("error"):
            head += _tr('tui.panes.error', p0=p['error'])
        self.query_one("#px-head", Static).update(head)
        self.query_one("#px-toggle", Button).label = _tr('tui.panes.stop') if p.get("running") else _tr('tui.panes.start')
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
            self.app.act(_tr('tui.panes.stopping_proxy'), "proxy_stop", journal="proxy stop")
        else:
            self.app.act(_tr('tui.panes.starting_proxy'), "proxy_start", journal="proxy start")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        mode = (event.pressed.id or "")[5:]
        if mode and mode != (self.app.data("proxy") or {}).get("mode", "pac"):
            self.app.act(_tr('tui.panes.proxy_mode', p0=mode), "proxy_set_mode", mode, journal=f"proxy mode {mode}")

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
            self.app.act(_tr('tui.panes.application', p0=name), "proxy_set_apps", [*apps, name], journal=f"proxy apps +{name}")

    def action_remove_app(self) -> None:
        name = selected_key(self.query_one("#px-apps", DataTable))
        if name:
            self.app.act(_tr('tui.panes.remove', p0=name), "proxy_set_apps", [a for a in self._apps() if a != name], journal=f"proxy apps -{name}")


# --- hosts -----------------------------------------------------------------------------------------------------

class HostsPane(Pane):
    KEYS = ("hosts", "hosts_state")

    def compose(self) -> ComposeResult:
        yield Static("…", id="hs-head", markup=False)
        with Horizontal(classes="row"):
            yield Static(_tr('tui.panes.hosts_override'), markup=False, classes="name")
            yield Switch(id="hs-enabled")
        yield Static(_tr('tui.panes.providers_and_their_assigned_lists_enter_to_sele'), markup=False, classes="dim")
        yield DataTable(id="hs-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one("#hs-table", DataTable)
        t.add_column(_tr('tui.panes.provider'), key="name")
        t.add_column(_tr('tui.panes.type'), key="type")
        t.add_column(_tr('tui.panes.lists'), key="lists")
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
            applied = _tr('tui.panes.applied') if st.get("applied") else _tr('tui.panes.not_applied')
            self.query_one("#hs-head", Static).update(
                _tr('tui.panes.entries', p0=tag(st.get('enabled'), _tr('tui.panes.enabled'), _tr('tui.panes.disabled')), p1=applied, p2=st.get('count', 0)))
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
            self.app.act(_tr('tui.panes.enabling_hosts') if want else _tr('tui.panes.disabling_hosts'), "hosts_set_enabled", want,
                         journal="hosts on" if want else "hosts off")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        pid = event.row_key.value
        names = [i["name"] for i in (self.app.data("hosts") or {}).get("lists") or []]

        def chosen(result):
            if result is None:
                return
            mapping = {**self._assignments(), pid: result}
            self.app.act(_tr('tui.panes.lists_for_provider', p0=pid), "hosts_set_assignments", {k: v for k, v in mapping.items() if v},
                         journal=f"hosts assign {pid}={','.join(result)}")

        self.app.push_screen(ListPicker(_tr('tui.panes.lists_for_provider_255', p0=pid), names, self._assignments().get(pid) or []), chosen)


# --- DNS -----------------------------------------------------------------------------------------------------------

TRIAL_SECONDS = 15


class DnsPane(Pane):
    KEYS = ("dns",)
    BINDINGS = [*Pane.BINDINGS, Binding("r", "reset", _tr('tui.panes.reset_to_dhcp'))]

    def compose(self) -> ComposeResult:
        yield Static("", id="dn-trial", markup=False)
        with Horizontal(id="dn-buttons", classes="row hidden"):
            yield Button(_tr('tui.panes.keep'), id="dn-keep")
            yield Button(_tr('tui.panes.restore_now'), id="dn-revert")
        yield Static(_tr('tui.panes.adapters_r_to_reset_the_selected_adapter_to_dhcp'), markup=False, classes="dim")
        yield DataTable(id="dn-adapters", cursor_type="row")
        yield Static(_tr('tui.panes.providers_enter_to_apply_with_rollback_after_s', p0=TRIAL_SECONDS), markup=False, classes="dim")
        yield DataTable(id="dn-providers", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        a = self.query_one("#dn-adapters", DataTable)
        a.add_column("№", key="i", width=4)
        a.add_column(_tr('tui.panes.adapter'), key="name")
        a.add_column(_tr('tui.panes.state'), key="status")
        a.add_column("DNS", key="dns")
        p = self.query_one("#dn-providers", DataTable)
        p.add_column(_tr('tui.panes.provider'), key="name")
        p.add_column(_tr('tui.panes.servers'), key="servers")
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
            "\n".join(_tr('tui.panes.dns_trial_on_adapter_rollback_in_s_keep_or_resto',
                p0=t.get('adapter'),
                p1=t.get('provider'),
                p2=t.get('seconds_left'),
            ) for t in trials))
        if self.app.error("dns"):
            self.query_one("#dn-trial", Static).update(_tr('tui.panes.could_not_load_dns', p0=self.app.error('dns')))

    def _adapter(self):
        key = selected_key(self.query_one("#dn-adapters", DataTable))
        return int(key) if key is not None else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if event.data_table.id != "dn-providers":
            return
        adapter, pid = self._adapter(), event.row_key.value
        if adapter is None:
            self.app.status(_tr('tui.panes.select_an_adapter_in_the_top_table_first'), error=True)
            return
        self.app.confirm(_tr('tui.panes.set_dns_on_adapter_if_not_confirmed_within_s_the', p0=pid, p1=adapter, p2=TRIAL_SECONDS),
                         lambda: self.app.act(_tr('tui.panes.dns_on_adapter', p0=pid, p1=adapter), "dns_set_trial", adapter, pid, TRIAL_SECONDS,
                                              journal=f"dns trial {adapter} {pid}"))

    def action_reset(self) -> None:
        adapter = self._adapter()
        if adapter is None:
            return
        self.app.confirm(_tr('tui.panes.reset_dns_for_adapter_to_automatic_dhcp', p0=adapter),
                         lambda: self.app.act(_tr('tui.panes.reset_dns_for_adapter', p0=adapter), "dns_reset", adapter, journal=f"dns reset {adapter}"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dn-keep":
            event.stop()
            self.app.act(_tr('tui.panes.dns_kept'), "dns_trial_confirm", journal="dns trial-confirm")
        elif event.button.id == "dn-revert":
            event.stop()
            self.app.act(_tr('tui.panes.dns_restored'), "dns_trial_revert", journal="dns trial-revert")


# --- Telegram-прокси ---------------------------------------------------------------------------------------------------------

class TgPane(Pane):
    KEYS = ("tg", "tg_stats")

    def compose(self) -> ComposeResult:
        yield Static("…", id="tg-head", markup=False)
        with Horizontal(classes="row"):
            yield Button(_tr('tui.panes.start'), id="tg-toggle")
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
        return _tr('tui.panes.tg_proxy_server_port_secret_hidden', p0=t.get('host'), p1=t.get('port'))

    def render_state(self) -> None:
        t = self.app.data("tg")
        if t is None:
            self.query_one("#tg-head", Static).update(_tr('tui.panes.no_telegram_proxy_data'))
            return
        head = tag(t.get("running"))
        if t.get("version"):
            head += _tr('tui.panes.core', p0=t['version'])
        if t.get("error"):
            head += _tr('tui.panes.error', p0=t['error'])
        self.query_one("#tg-head", Static).update(head)
        self.query_one("#tg-toggle", Button).label = _tr('tui.panes.stop') if t.get("running") else _tr('tui.panes.start')
        self.query_one("#tg-info", Static).update(
            _tr('tui.panes.address_autostart_link_full_link_chimera_tg_link',
                p0=t.get('host'),
                p1=t.get('port'),
                p2=_tr('tui.panes.yes') if t.get('autostart') else _tr('tui.panes.no'),
                p3=self.masked_link(t),
            ))
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
            self.app.act(_tr('tui.panes.stopping_telegram_proxy'), "tg_stop", journal="tg stop")
        else:
            self.app.act(_tr('tui.panes.starting_telegram_proxy'), "tg_start", journal="tg start")


# --- логи ---------------------------------------------------------------------------------------------------------------------------

LOG_FILES = (("winws", "winws.log", "winws_log"), ("proxy", "proxy.log", "proxy_log"), ("tg", "tgproxy.log", "tg_log"))
LOG_LINES = 1000


class LogsPane(Pane):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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

THEMES = (("system", _tr('tui.panes.system')), ("light", _tr('tui.panes.light')), ("dark", _tr('tui.panes.dark')))


class SettingsPane(Pane):
    KEYS = ("config", "app")

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("", id="se-info", markup=False)
            yield Static(_tr('tui.panes.chimera_window_theme'), markup=False, classes="dim")
            with RadioSet(id="se-theme"):
                for value, title in THEMES:
                    yield RadioButton(title, id=f"theme-{value}")
            yield Static("", id="se-lang", markup=False)
            with RadioSet(id="se-language", classes="hidden"):
                for value, key in (("auto", "tui.settings.language.auto"), ("ru", "tui.settings.language.ru"),
                                   ("en", "tui.settings.language.en")):
                    yield RadioButton(_tr(key), id=f"lang-{value}")

    def sources(self) -> list:
        return [("config", "config_read", (), 5)]

    def focus_primary(self) -> None:
        self.query_one("#se-theme", RadioSet).focus()

    def render_state(self) -> None:
        a, cfg = self.app.data("app") or {}, self.app.data("config") or {}
        self.query_one("#se-info", Static).update(
            _tr('tui.panes.chimera_version_administrator_rights_interface_m',
                p0=a.get('version', '?'),
                p1=_tr('tui.panes.yes') if a.get('admin') else _tr('tui.panes.no'),
                p2=cfg.get('interface', '?'),
            ))
        theme = cfg.get("theme", "system")
        btn = self.query_one(f"#theme-{theme}", RadioButton) if theme in dict(THEMES) else None
        if btn is not None and not btn.value:
            btn.value = True
        lang = self.query_one("#se-lang", Static)
        setting = cfg.get("lang", cfg.get("language"))
        lang.update(_tr('tui.panes.language', p0=setting) if setting is not None else "")
        lang.set_class(setting is None, "hidden")
        choices = self.query_one("#se-language", RadioSet)
        choices.set_class("lang" not in cfg, "hidden")
        if setting in ("auto", "ru", "en") and "lang" in cfg:
            selected = self.query_one(f"#lang-{setting}", RadioButton)
            if not selected.value:
                selected.value = True

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        pressed = event.pressed.id or ""
        if pressed.startswith("lang-"):
            language = pressed[5:]
            if language != (self.app.data("config") or {}).get("lang", "auto"):
                self.app.act(_tr("tui.settings.language_changed", setting=language),
                             "config_set", "lang", language, journal=f"config set lang {language}")
            return
        theme = pressed[6:]
        if theme and theme != (self.app.data("config") or {}).get("theme", "system"):
            self.app.act(_tr('tui.panes.window_theme', p0=theme), "config_set", "theme", theme, journal=f"config set theme {theme}")

