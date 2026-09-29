"""Связка обмена конфигом (modules/shareconfig.py) с живой программой.

snapshot() читает настройки менеджеров Api, а изменения идут теми же методами Api, что и из
интерфейса, — поэтому применяются «на лету» (списки доходят до winws/прокси/hosts, запущенные
модули перезапускаются сами, где это неизбежно). Секреты сюда не попадают: ссылка прокси,
секрет и адрес прослушивания Telegram-прокси в snapshot не читаются вовсе.
"""

from modules.i18n import t as _tr

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
        return res.get("data")
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
