"""Связка обмена конфигом (modules/shareconfig.py) с живой программой.

snapshot() читает настройки менеджеров Api, а изменения идут теми же методами Api, что и из
интерфейса, — поэтому применяются «на лету» (списки доходят до winws/прокси/hosts, запущенные
модули перезапускаются сами, где это неизбежно). Секреты сюда не попадают: ссылка прокси,
секрет и адрес прослушивания Telegram-прокси в snapshot не читаются вовсе.
"""

from modules.i18n import t as _tr

from copy import deepcopy

from modules import appconfig, dns_providers, domains
from modules.hosts import manager as hosts_manager
from modules.proxy import manager as proxy_manager
from modules.tgproxy import manager as tg_manager
from modules.winws import filters
from modules.winws import manager as winws_manager

_TG_ADVANCED = ("disable_secure", "fallback_cfproxy", "cfproxy_user_domains", "cfproxy_worker_domains",
                "fake_tls_domain", "dc_redirects", "proxy_protocol", "force_test_dc")


def _check(res):
    """Ответ метода Api ({ok, data|error}) -> данные, либо исключение с текстом ошибки."""
    if isinstance(res, dict) and "ok" in res:
        if not res["ok"]:
            raise RuntimeError(res.get("error") or _tr('msg.ui.shareops.unknown_error'))
        data = res.get("data")
        if isinstance(data, dict) and (data.get("apply_error") or data.get("apply_errors")):
            raise RuntimeError(_tr("msg.backup.apply_failed"))
        return data
    return res


class ShareOps:
    def __init__(self, api):
        self.api = api

    # --- текущее состояние ---------------------------------------------------------------

    def snapshot(self) -> dict:
        a = self.api
        all_providers = dns_providers.load_all()
        custom = [p for p in all_providers if not p.get("builtin")]
        lists = {n: domains.read_raw(n) for n in domains.available_lists()}
        strategies = [s["id"] for s in a.winws.strategies()]
        tg = a.tg.config
        return {
            "lists": lists,
            "proxy": {"mode": a.proxy.config.get("mode", "pac"), "lists": list(a.proxy.config.get("lists") or []),
                      "apps": list(a.proxy.config.get("apps") or [])},
            "hosts": {"assignments": a.hosts.assignments(),
                      "providers": [p for p in custom if p.get("unblock")]},
            "dns": {"providers": [p for p in custom if not p.get("unblock")]},
            "telegram": {"port": tg.get("port"), "advanced": {k: tg[k] for k in _TG_ADVANCED if k in tg}},
            "winws": {"strategy": a.winws.config.get("last_strategy"), "lists": list(a.winws.config.get("lists") or []),
                      "game": {"mode": filters.game_mode(), **filters.game_ranges()},
                      "ipset": filters.ipset_state()},
            "known": {"strategies": strategies,
                      "provider_ids": [p["id"] for p in all_providers] + [p["id"] for p in a.hosts.providers()],
                      "list_names": list(lists)},
        }

    # --- изменения (через методы Api, как из интерфейса) -------------------------------------

    def list_write(self, name, text):
        _check(self.api.lists_save(name, text))

    def add_provider(self, spec) -> str:
        p = dns_providers.add(spec["name"], servers=spec.get("servers") or [], ipv6=spec.get("ipv6") or [],
                              doh=spec.get("doh") or "", dot=spec.get("dot") or "",
                              unblock=bool(spec.get("unblock")), filtering=bool(spec.get("filter")))
        return p["id"]

    def set_proxy(self, mode, lists, apps):
        if mode:
            _check(self.api.proxy_set_mode(mode))
        if lists is not None:
            _check(self.api.proxy_set_lists(lists))
        if apps is not None:
            _check(self.api.proxy_set_apps(apps))

    def set_assignments(self, mapping):
        _check(self.api.hosts_set_assignments(mapping))

    def tg_set_port(self, port):
        cfg = self.api.tg.config
        _check(self.api.tg_set_config(cfg.get("host", "127.0.0.1"), port, cfg.get("secret", ""), bool(cfg.get("autostart"))))

    def tg_set_advanced(self, options):
        _check(self.api.tg_set_advanced(options))

    def winws_select(self, strategy_id):
        self.api.winws.select_strategy(strategy_id)

    def winws_set_lists(self, names):
        _check(self.api.winws_set_lists(names))

    def game_set(self, mode, tcp, udp):
        _check(self.api.game_filter_set(mode, tcp, udp))

    def ipset_set(self, mode):
        _check(self.api.ipset_set(mode))

    # --- файлы для снимка перед импортом --------------------------------------------------------

    def backup_files(self, sections, list_names):
        files = []
        if "proxy" in sections:
            files.append(proxy_manager.STATE_PATH)
        if "hosts" in sections:
            files += [hosts_manager.STATE_PATH, dns_providers.USER_PATH]
        if "dns" in sections:
            files.append(dns_providers.USER_PATH)
        if "telegram" in sections:
            files.append(tg_manager.STATE_PATH)
        if "winws" in sections:
            files += [winws_manager.STATE_PATH, appconfig.CONFIG_PATH]
        for n in list_names:
            files.append(domains.LISTS_DIR / f"{n}.txt")
        seen, res = set(), []
        for f in files:
            if f not in seen:
                seen.add(f)
                res.append(f)
        return res


    # --- local snapshots (private values stay inside the application) -----------------

    def _current_states(self):
        from modules import configbackups
        return {
            "proxy": configbackups.normalize("proxy", self.api.proxy.config),
            "telegram": configbackups.normalize("telegram", self.api.tg.config),
            "winws": configbackups.normalize("winws", self.api.winws.config),
            "hosts": configbackups.normalize("hosts", self.api.hosts._load_state()),
            "dns": configbackups.normalize("dns", [p for p in dns_providers.load_all() if not p.get("builtin")]),
            "config": configbackups.normalize("config", appconfig.load()),
            "filters": configbackups.normalize("filters", filters.ipset_snapshot()),
        }

    def validate_backup(self, backup):
        from modules.errors import ChimeraValueError
        from modules.hosts import static_providers
        a = self.api
        states = backup["states"]
        if backup.get("complete_lists"):
            saved_names = {name.casefold() for name in backup["lists"]}
            for name in domains.available_lists():
                if name.casefold() not in saved_names:
                    backup["lists"][name] = None
        current = self._current_states()
        deleted = {n.casefold() for n, text in backup["lists"].items() if text is None}
        # Removing an imported list must also remove its live connections. Save these
        # dependent sections in the inverse snapshot so the operation stays reversible.
        if deleted:
            for sid in ("proxy", "winws"):
                if sid not in states and any(n.casefold() in deleted for n in current[sid]["lists"]):
                    states[sid] = deepcopy(current[sid])
                    states[sid]["lists"] = [n for n in states[sid]["lists"] if n.casefold() not in deleted]
            if "hosts" not in states and any(isinstance(v, list) and any(n.casefold() in deleted for n in v)
                                              for v in current["hosts"]["assignments"].values()):
                states["hosts"] = deepcopy(current["hosts"])
                states["hosts"]["assignments"] = {
                    pid: ([n for n in value if n.casefold() not in deleted] if isinstance(value, list) else value)
                    for pid, value in states["hosts"]["assignments"].items()}
                states["hosts"]["assignments"] = {pid: value for pid, value in states["hosts"]["assignments"].items() if value}
        providers = dns_providers.load_all()
        builtin = {p["id"] for p in providers if p.get("builtin")}
        static = {p["id"] for p in static_providers.providers()}
        if "dns" in states:
            if any(p["id"] in builtin | static for p in states["dns"]):
                raise ChimeraValueError("err.backup.invalid", name="dns_providers.user.json")
            known_ids = builtin | static | {p["id"] for p in states["dns"]}
            if "hosts" not in states:
                states["hosts"] = deepcopy(current["hosts"])
                states["hosts"]["assignments"] = {pid: value for pid, value in current["hosts"]["assignments"].items()
                                                   if pid in known_ids}
        else:
            known_ids = {p["id"] for p in providers} | static
        available = {n.casefold() for n in domains.available_lists()}
        for name, text in backup["lists"].items():
            if text is None:
                available.discard(name.casefold())
            else:
                available.add(name.casefold())
        for sid in ("proxy", "winws"):
            if sid in states and any(n.casefold() not in available for n in states[sid]["lists"]):
                raise ChimeraValueError("err.backup.invalid", name=sid)
        if "hosts" in states:
            for pid, value in states["hosts"]["assignments"].items():
                if pid not in known_ids or (value is True and pid not in static) or (
                        isinstance(value, list) and (pid in static or any(n.casefold() not in available for n in value))):
                    raise ChimeraValueError("err.backup.invalid", name="hosts.json")
        touched = {n.casefold() for n in backup["lists"]}
        proxy_used = any(n.casefold() in touched for n in a.proxy.config.get("lists", []))
        game_changed = "config" in states and any(
            states["config"].get(k) != current["config"].get(k)
            for k in ("game_filter", "game_filter_tcp", "game_filter_udp"))
        winws_used = ("winws" in states or game_changed or "filters" in states or
                      any(n.casefold() in touched for n in a.winws.config.get("lists", [])))
        if winws_used and a.winws.running and not a.winws._ours_alive:
            raise ChimeraValueError("err.winws.foreign")
        if ("proxy" in states or proxy_used) and a.proxy.running and not a.proxy._ours_alive:
            raise ChimeraValueError("err.backup.foreign_proxy")
        if "winws" in states:
            sid = states["winws"].get("last_strategy")
            if sid is not None and sid not in {s["id"] for s in a.winws.strategies()}:
                raise ChimeraValueError("err.backup.invalid", name="winws.json")
            if a.winws.running and not a.winws._ours_alive:
                raise ChimeraValueError("err.winws.foreign")

    def backup_snapshot(self, target):
        current = self._current_states()
        lists = {n.casefold(): domains.read_raw(n) for n in domains.available_lists()}
        states = {sid: deepcopy(current[sid]) for sid in target["states"]}
        # Rebuilding provider assignments can change the hosts cache, even for a DNS-only snapshot.
        if "dns" in states:
            states.setdefault("hosts", deepcopy(current["hosts"]))
        return {"states": states, "lists": {n: lists.get(n.casefold()) for n in target["lists"]},
                "runtime": {sid: bool(getattr(manager, "running", False)) for sid, manager in
                            (("proxy", self.api.proxy), ("telegram", self.api.tg), ("winws", self.api.winws)) if sid in states}}

    def backup_state(self, sections, list_names):
        current = self._current_states()
        selected = set(sections) - {"lists"}
        if "winws" in selected:
            selected.update(("config", "filters"))
        if "hosts" in selected:
            selected.add("dns")
        return {"states": {sid: current[sid] for sid in selected},
                "lists": {name: domains.read_raw(name) if name in domains.available_lists() else None for name in list_names}}

    def backup_requires_admin(self, target):
        a = self.api
        if "hosts" in target["states"]:
            return True
        if ("winws" in target["states"] or "filters" in target["states"]) and a.winws.running:
            return True
        if "config" in target["states"] and a.winws.running:
            config = target["states"]["config"]
            current = appconfig.load()
            if any(config.get(k) != current.get(k) for k in ("game_filter", "game_filter_tcp", "game_filter_udp")):
                return True
        if "proxy" in target["states"] and a.proxy.running:
            return target["states"]["proxy"].get("mode") != "pac" or a.proxy.config.get("mode") != "pac"
        return any(name in domains.available_lists() and text != domains.read_raw(name)
                   for name, text in target["lists"].items()
                   if any(isinstance(names, list) and name in names for names in a.hosts.assignments().values()))

    @staticmethod
    def backup_is_admin():
        from ui.api import is_admin
        return is_admin()

    def restore_snapshot(self, target, rollback=False):
        a = self.api
        states = target["states"]
        before_config = appconfig.load()
        # Defer list propagation until all dependent settings are in place. The final
        # apply reaches the same winws/proxy/hosts consumers as lists_save.
        for name, text in target["lists"].items():
            if text is None:
                if name in domains.available_lists():
                    domains.delete_list(name)
            else:
                domains.save_raw(name, text)
        if "dns" in states:
            dns_providers.restore_user(states["dns"])
        before_filters = filters.ipset_snapshot()
        if "filters" in states:
            filters.restore_ipset_snapshot(states["filters"])
        if "config" in states:
            appconfig.restore_values(states["config"])
            if getattr(a, "push", None):
                from modules import i18n
                with i18n.request_language(None):
                    a._push("langChanged", i18n.state())
        for sid, manager in (("proxy", a.proxy), ("telegram", a.tg), ("winws", a.winws), ("hosts", a.hosts)):
            if sid in states:
                _check(manager.restore_config(states[sid]))
        now = appconfig.load()
        game_changed = "config" in states and any(before_config.get(k) != now.get(k)
                                                   for k in ("game_filter", "game_filter_tcp", "game_filter_udp"))
        filters_changed = "filters" in states and before_filters != states["filters"]
        if game_changed or filters_changed:
            a._restart_winws_if_running()
        if target["lists"]:
            _check(a.lists_apply())
        if rollback:
            for sid, manager in (("proxy", a.proxy), ("telegram", a.tg), ("winws", a.winws)):
                if not target.get("runtime", {}).get(sid) or manager.running:
                    continue
                if sid == "winws":
                    manager.start(manager.config["last_strategy"])
                else:
                    manager.start()
