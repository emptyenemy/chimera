"""Операции автонастройки над настоящими модулями: захват и откат состояния, варианты, проверка.

Движок (modules/autotune/engine.py) зовёт эти методы из своего потока; менеджер сессии
держит при этом общую блокировку изменений. Здесь — только «как»: какой метод модуля
вызвать и что сохранить, чтобы потом вернуть ровно как было.
"""

import time
from copy import deepcopy

from modules import blockcheck, configbackups, dataupdate, domains
from modules.autotune import memory, provider as provider_mod, targets as targets_mod
from modules.errors import ChimeraError
from modules.hosts.manager import BLOCK_RE, replace_block
from ui.shareops import ShareOps

# Сколько дать изменению вступить в силу перед проверкой. winws.start() сам ждёт секунду,
# а hosts и DNS читает служба DNS-клиента Windows.
SETTLE = {"strategy": 0.5, "hosts": 0.5, "dns": 1.0, "proxy": 1.5}


def _merged(base, extra):
    return list(dict.fromkeys(list(base) + list(extra)))


class AutotuneOps:
    def __init__(self, api, sleep=time.sleep):
        self.api, self.sleep = api, sleep
        self._before = None

    # --- каталог и проверка -------------------------------------------------------------

    def services(self):
        # «всегда напрямую» — банки и госсервисы: их не разблокируют, им нужен российский IP
        direct = set(self.api.proxy.config.get("direct_lists") or [])
        return [{"name": i["name"], "targets": targets_mod.targets(i["name"], i["entries"])}
                for i in domains.list_index() if i["name"] not in direct]

    def targets(self, name):
        return targets_mod.targets(name, domains.load_list(name))

    def check(self, domain):
        return blockcheck.check(domain, socks_addr=self.api._proxy_socks_addr(domain))

    def settle(self, step):
        self.sleep(SETTLE.get(step, 0))

    def network_key(self):
        return memory.network_key(self.api.dns.adapters())

    @staticmethod
    def require_admin():
        from ui.api import is_admin
        if not is_admin():
            raise ChimeraError("err.autotune.admin")

    def _adapter(self):
        for a in self.api.dns.adapters():
            if a.get("status") == "Up" and a.get("physical") and a.get("ipv4"):
                return a
        return None

    # --- состояние целиком ---------------------------------------------------------------

    def capture(self):
        api = self.api
        winws, proxy = api.winws.state(), api.proxy.state()
        block = BLOCK_RE.search(api.hosts._read_hosts())
        adapter = self._adapter()
        before = {
            "winws": {"running": bool(winws.get("running")), "current": winws.get("current"),
                      "last_strategy": api.winws.config.get("last_strategy"),
                      "lists": list(api.winws.config.get("lists") or []), "external": bool(winws.get("external"))},
            "hosts": {"state": deepcopy(api.hosts._load_state()), "block": block.group() if block else None},
            "proxy": {"running": bool(proxy.get("running")), "mode": api.proxy.config.get("mode", "pac"),
                      "lists": list(api.proxy.config.get("lists") or []), "external": bool(proxy.get("external"))},
            "dns": None if adapter is None else {
                "adapter": adapter["index"], "previous": api.dns._snapshot(adapter["index"]),
                "was_ours": adapter["index"] in api.dns.changed_adapters()},
        }
        self._before = before
        return deepcopy(before)

    def snapshot(self):
        configbackups.create_snapshot(ShareOps(self.api).backup_state(("winws", "proxy", "hosts"), ()), kind="auto")

    def restore(self, before):
        """Вернуть всё, что могла тронуть автонастройка. Шаги независимы: сбой одного не мешает остальным."""
        self._before = before
        failed = []
        for part in (self._restore_dns, self._restore_proxy, self._restore_hosts, self._restore_winws):
            try:
                part(before)
            except Exception as e:
                failed.append(e)
        if failed:
            raise failed[0]

    def _restore_winws(self, before):
        b, winws = before["winws"], self.api.winws
        if b["external"]:
            return   # чужой winws не трогали
        if list(winws.config.get("lists") or []) != b["lists"]:
            winws.set_lists(b["lists"])
        state = winws.state()
        if state.get("running") and (not b["running"] or state.get("current") != b["current"]):
            winws.stop()
        if b["running"] and not winws.running:
            winws.start(b["current"])
        if winws.config.get("last_strategy") != b["last_strategy"]:
            winws._save({**winws.config, "last_strategy": b["last_strategy"]})

    def _restore_hosts(self, before):
        b, hosts = before["hosts"], self.api.hosts
        configbackups.normalize("hosts", b["state"])
        block = b["block"]
        if block is not None and (not isinstance(block, str) or not BLOCK_RE.fullmatch(block)):
            raise ChimeraError("err.autotune.invalid_record")
        current = hosts._read_hosts()
        text = replace_block(current, block)
        if text != current:
            hosts._write_hosts(text)
        hosts._save_state(b["state"])

    def _restore_proxy(self, before):
        b, proxy = before["proxy"], self.api.proxy
        if b["external"]:
            return
        if list(proxy.config.get("lists") or []) != b["lists"]:
            proxy.set_lists(b["lists"])
        if proxy.running and not b["running"]:
            proxy.stop()
        if proxy.config.get("mode", "pac") != b["mode"]:
            proxy.set_mode(b["mode"])
        if b["running"] and not proxy.running:
            proxy.start()

    def _restore_dns(self, before):
        b = before["dns"]
        if b is None:
            return
        dns = self.api.dns
        if dns._snapshot(b["adapter"]) != b["previous"]:
            dns.restore_adapter(b["adapter"], b["previous"], b["was_ours"])

    # --- стратегии -------------------------------------------------------------------------

    def winws_external(self):
        return bool(self.api.winws.state().get("external"))

    def strategies(self):
        return [s["id"] for s in self.api.winws.strategies()]

    def prepare_strategy(self, services):
        self.api.winws.set_lists(_merged(self._before["winws"]["lists"], services))

    def apply_strategy(self, strategy_id):
        self.api.winws.start(strategy_id)

    def commit_strategy(self, services):
        self.api.winws.set_lists(_merged(self._before["winws"]["lists"], services))

    def restore_strategy(self):
        self._restore_winws(self._before)

    # --- hosts -----------------------------------------------------------------------------

    def hosts_providers(self):
        # статический Flowseal назначается целиком, а не на список — в переборе его нет
        return [p["id"] for p in self.api.hosts.visible_providers()
                if p.get("type") == "dns" and (p.get("doh") or p.get("servers"))]

    def hosts_assignment(self, service):
        for provider, names in self.api.hosts.assignments().items():
            if isinstance(names, list) and service in names:
                return provider
        return None

    def assign_hosts(self, service, provider):
        hosts = self.api.hosts
        mapping = {pid: ([n for n in names if n != service] if isinstance(names, list) else names)
                   for pid, names in hosts.assignments().items()}
        if provider is not None:
            mapping[provider] = [*mapping.get(provider, []), service]
        hosts.set_assignments(mapping)
        if provider is not None and not hosts._load_state().get("enabled", True):
            hosts.set_enabled(True)

    # --- DNS -------------------------------------------------------------------------------

    def dns_available(self):
        return self._before is not None and self._before["dns"] is not None

    def dns_providers(self, unblock=False):
        return [p["id"] for p in self.api.dns.list_providers() if bool(p.get("unblock")) == unblock and p.get("servers")]

    def apply_dns(self, provider):
        # без пробы DnsJumper: откат даёт сама сессия, и плашка «Оставить» на вкладке DNS не нужна
        self.api.dns.set_dns(self._before["dns"]["adapter"], provider)

    def keep_dns(self):
        pass

    def revert_dns(self):
        self._restore_dns(self._before)

    # --- прокси ----------------------------------------------------------------------------

    def proxy_available(self):
        state = self.api.proxy.state()
        return bool(state.get("parsed")) and bool((state.get("core") or {}).get("present")) and not state.get("external")

    def apply_proxy(self, services):
        proxy = self.api.proxy
        proxy.set_lists(_merged(self._before["proxy"]["lists"], services))
        if not proxy.running:
            proxy.start()

    def commit_proxy(self, services):
        self.api.proxy.set_lists(_merged(self._before["proxy"]["lists"], services))

    def restore_proxy(self):
        self._restore_proxy(self._before)

    # --- провайдер и отчёт -----------------------------------------------------------------

    @staticmethod
    def provider_map():
        return provider_mod.load_map()

    def lookup_provider(self):
        proxy = self.api.proxy
        if proxy.running and proxy.config.get("mode") == "tun":
            return None   # весь трафик в туннеле: RIPEstat увидел бы адрес сервера прокси
        return provider_mod.lookup()

    @staticmethod
    def about():
        from modules.version import VERSION
        return {"app": VERSION, "data": dataupdate.DataUpdater().installed()}
