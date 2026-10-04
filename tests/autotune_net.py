"""Модель сети для автонастройки: что открывается при каких настройках.

Правило домена — функция от состояния (стратегия, hosts, DNS, прокси), которая
возвращает (статус, мс). Операции меняют состояние и записывают вызовы, так что
тест видит и итог, и путь к нему. Ею пользуются тесты движка и менеджера
и живой смоук страницы (tools/smoke_autotune.py)."""

from copy import deepcopy

from modules.autotune.targets import CANARY


def opens(ms=50):
    return lambda state: ("ok", ms)


def blocked_unless(fix, ms=50, status="blocked"):
    """Открывается, только если fix(state) истинно; иначе status."""
    return lambda state: ("ok", ms(state) if callable(ms) else ms) if fix(state) else (status, None)


class FakeOps:
    def __init__(self, targets, rules, *, strategies=("general", "alt", "alt2"), hosts=("xbox", "comss"),
                 dns_plain=("cloudflare", "google"), dns_unblock=("comss-dns",), proxy=False, external=False,
                 admin=True, canary=None):
        self.targets_map = dict(targets)
        self.rules = dict(rules)
        self.canary = canary or {}
        self.strategy_ids, self.hosts_ids = list(strategies), list(hosts)
        self.dns_plain, self.dns_unblock = list(dns_plain), list(dns_unblock)
        self.proxy_ready, self.external, self.admin = proxy, external, admin
        self.state = {"strategy": None, "winws_lists": [], "hosts": {}, "dns": None, "proxy": []}
        self.calls, self.fail_apply, self.hooks = [], set(), {}
        self._dns_before = None
        self.restored = []
        self.providers, self.provider, self.lookups = {}, None, 0   # карта провайдеров и ответ RIPEstat

    # --- каталог и проверка -------------------------------------------------------------

    def services(self):
        return [{"name": n, "targets": list(t)} for n, t in self.targets_map.items()]

    def targets(self, name):
        return list(self.targets_map.get(name, []))

    def check(self, domain):
        rule = self.rules.get(domain) or self.canary.get(domain) or (opens() if domain in CANARY else None)
        status, ms = rule(self.state) if rule else ("error", None)
        return {"status": status, "ms": ms}

    def settle(self, step):
        pass

    def network_key(self):
        return "net"

    def provider_map(self):
        return self.providers

    def lookup_provider(self):
        self.lookups += 1
        return self.provider

    @staticmethod
    def about():
        return {"app": "1.1.0", "data": "2026.10.01.1"}

    # --- состояние целиком ----------------------------------------------------------------

    def require_admin(self):
        if not self.admin:
            from modules.errors import ChimeraError
            raise ChimeraError("err.autotune.admin")

    def capture(self):
        return deepcopy(self.state)

    def restore(self, before):
        self.restored.append(deepcopy(before))
        self.state = deepcopy(before)

    def snapshot(self):
        self.calls.append(("snapshot",))

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if (name, *args) in self.fail_apply:
            raise RuntimeError(f"{name} failed")
        hook = self.hooks.get(name)
        if hook:
            hook(*args)

    # --- стратегии -------------------------------------------------------------------------

    def winws_external(self):
        return self.external

    def strategies(self):
        return list(self.strategy_ids)

    def prepare_strategy(self, services):
        self._call("prepare_strategy", tuple(services))
        self._winws_before = (self.state["strategy"], list(self.state["winws_lists"]))
        self.state["winws_lists"] = list(dict.fromkeys(self.state["winws_lists"] + list(services)))

    def apply_strategy(self, sid):
        self._call("apply_strategy", sid)
        self.state["strategy"] = sid

    def commit_strategy(self, services):
        self._call("commit_strategy", tuple(services))
        self.state["winws_lists"] = list(dict.fromkeys(self._winws_before[1] + list(services)))

    def restore_strategy(self):
        self._call("restore_strategy")
        self.state["strategy"], self.state["winws_lists"] = self._winws_before[0], list(self._winws_before[1])

    # --- hosts -----------------------------------------------------------------------------

    def hosts_providers(self):
        return list(self.hosts_ids)

    def hosts_assignment(self, service):
        return self.state["hosts"].get(service)

    def assign_hosts(self, service, provider):
        self._call("assign_hosts", service, provider)
        if provider is None:
            self.state["hosts"].pop(service, None)
        else:
            self.state["hosts"][service] = provider

    # --- DNS -------------------------------------------------------------------------------

    def dns_available(self):
        return True

    def dns_providers(self, unblock=False):
        return list(self.dns_unblock if unblock else self.dns_plain)

    def apply_dns(self, provider):
        self._call("apply_dns", provider)
        if self._dns_before is None:
            self._dns_before = (self.state["dns"],)
        self.state["dns"] = provider

    def keep_dns(self):
        self._call("keep_dns")
        self._dns_before = None

    def revert_dns(self):
        self._call("revert_dns")
        if self._dns_before is not None:
            self.state["dns"] = self._dns_before[0]
            self._dns_before = None

    # --- прокси ----------------------------------------------------------------------------

    def proxy_available(self):
        return self.proxy_ready

    def apply_proxy(self, services):
        self._call("apply_proxy", tuple(services))
        self._proxy_before = list(self.state["proxy"])
        self.state["proxy"] = list(dict.fromkeys(self.state["proxy"] + list(services)))

    def commit_proxy(self, services):
        self._call("commit_proxy", tuple(services))
        self.state["proxy"] = list(dict.fromkeys(self._proxy_before + list(services)))

    def restore_proxy(self):
        self._call("restore_proxy")
        self.state["proxy"] = list(self._proxy_before)

    def applied(self, name):
        return [c[1] for c in self.calls if c[0] == name]
