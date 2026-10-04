"""Операции автонастройки над модулями: всё, что тронул подбор, возвращается ровно как было.

winws, прокси и DNS — заглушки с настоящей логикой состояния; hosts — настоящий HostsManager
на временных файлах (резолв подменён), чтобы откат блока hosts проверялся по байтам."""

import pytest

from modules.errors import ChimeraError
from modules.hosts import manager as hosts_mod
from modules.hosts.manager import HostsManager
from ui import api as api_mod
from ui.autotune import AutotuneOps


class Winws:
    def __init__(self, running=False, current=None, lists=(), external=False):
        self.config = {"last_strategy": current, "lists": list(lists)}
        self._running, self._current, self.external, self.log = running, current, external, []

    @property
    def running(self):
        return self._running

    def state(self):
        return {"running": self._running, "current": self._current if self._running else None, "external": self.external}

    def strategies(self):
        return [{"id": "general"}, {"id": "alt"}]

    def set_lists(self, names):
        self.config["lists"] = list(names)

    def start(self, sid):
        self.log.append(("start", sid))
        self._running, self._current = True, sid
        self.config["last_strategy"] = sid

    def stop(self):
        self.log.append(("stop",))
        self._running, self._current = False, None

    def _save(self, data):
        self.config = data


class Proxy:
    def __init__(self, running=False, mode="pac", lists=()):
        self.config = {"mode": mode, "lists": list(lists)}
        self._running = running

    @property
    def running(self):
        return self._running

    def state(self):
        return {"running": self._running, "parsed": {"server": "s"}, "core": {"present": True}, "external": False}

    def set_lists(self, names):
        self.config["lists"] = list(names)

    def set_mode(self, mode):
        self.config["mode"] = mode

    def start(self):
        self._running = True

    def stop(self):
        self._running = False


class Dns:
    def __init__(self):
        self.servers = {4: {"dns": ["192.168.1.1"], "static": False}}
        self.restored = []

    def adapters(self):
        return [{"index": 4, "status": "Up", "physical": True, "ipv4": ["192.168.1.10"], "guid": "{G}"}]

    def _snapshot(self, idx):
        return dict(self.servers[idx])

    def changed_adapters(self):
        return []

    def list_providers(self):
        return [{"id": "cloudflare", "servers": ["1.1.1.1"]}, {"id": "comss", "servers": ["83.220.169.155"], "unblock": True},
                {"id": "doh-only", "servers": []}]

    def set_dns(self, idx, provider):
        self.servers[idx] = {"dns": [provider], "static": True}

    def restore_adapter(self, idx, previous, was_ours):
        self.restored.append((idx, previous, was_ours))
        self.servers[idx] = dict(previous)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(hosts_mod, "is_admin", lambda: True)
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    monkeypatch.setattr(hosts_mod, "resolve_domains", lambda names, *a: [{"host": n, "ip": "10.0.0.1"} for n in names])
    hosts_file = tmp_path / "hosts"
    hosts_file.write_bytes(b"127.0.0.1 localhost\r\n# own line\r\n")
    hosts = HostsManager(state_path=tmp_path / "hosts.json", hosts_path=hosts_file)
    hosts._save_state({"enabled": True, "assignments": {"malw": ["discord"]}, "entries": []})
    api = type("A", (), {})()
    api.winws, api.proxy, api.hosts, api.dns = Winws(running=True, current="general", lists=["discord"]), Proxy(), hosts, Dns()
    api._proxy_socks_addr = lambda domain: None
    monkeypatch.setattr("modules.domains.list_info", lambda: [{"name": n} for n in ("discord", "youtube", "openai")])
    ops = AutotuneOps(api, sleep=lambda s: None)
    return ops, api, hosts_file


def test_everything_the_search_touched_comes_back_exactly(env):
    ops, api, hosts_file = env
    original_hosts = hosts_file.read_bytes()
    before = ops.capture()
    ops.prepare_strategy(["youtube"])
    ops.apply_strategy("alt")
    ops.commit_strategy(["youtube"])
    ops.assign_hosts("openai", "comss")
    ops.apply_dns("cloudflare")
    ops.apply_proxy(["openai"])
    assert api.winws.state()["current"] == "alt" and api.winws.config["lists"] == ["discord", "youtube"]
    assert b"openai" in hosts_file.read_bytes() and api.proxy.running and api.dns.servers[4]["static"]
    ops.restore(before)
    assert api.winws.state() == {"running": True, "current": "general", "external": False}
    assert api.winws.config == {"last_strategy": "general", "lists": ["discord"]}
    assert hosts_file.read_bytes() == original_hosts
    assert api.hosts.assignments() == {"malw": ["discord"]}
    assert api.dns.servers[4] == {"dns": ["192.168.1.1"], "static": False}
    assert not api.proxy.running and api.proxy.config["lists"] == []


def test_hosts_assignment_moves_a_list_between_providers_and_back(env):
    ops, api, _ = env
    ops.capture()
    ops.assign_hosts("discord", "comss")
    assert api.hosts.assignments() == {"comss": ["discord"]}
    assert ops.hosts_assignment("discord") == "comss"
    ops.assign_hosts("discord", "malw")
    assert api.hosts.assignments() == {"malw": ["discord"]}
    ops.assign_hosts("discord", None)
    assert api.hosts.assignments() == {} and ops.hosts_assignment("discord") is None


def test_disabled_hosts_are_switched_on_for_the_variant_and_off_again_on_restore(env):
    ops, api, _ = env
    api.hosts._save_state({"enabled": False, "assignments": {}, "entries": []})
    before = ops.capture()
    ops.assign_hosts("openai", "comss")
    assert api.hosts.state()["enabled"] is True and api.hosts.state()["applied"]
    ops.restore(before)
    assert api.hosts.state()["enabled"] is False and not api.hosts.state()["applied"]


def test_stopped_winws_is_stopped_again_after_the_search(env):
    ops, api, _ = env
    api.winws = Winws(running=False, current=None, lists=[])
    before = ops.capture()
    ops.apply_strategy("alt")
    ops.restore(before)
    assert not api.winws.running and api.winws.config["last_strategy"] is None


def test_foreign_winws_is_never_touched(env):
    ops, api, _ = env
    api.winws = Winws(running=True, current="general", external=True)
    before = ops.capture()
    assert ops.winws_external() is True
    ops.restore(before)
    assert api.winws.log == []


def test_a_failed_part_does_not_stop_the_others_and_is_reported(env, monkeypatch):
    ops, api, hosts_file = env
    before = ops.capture()
    ops.apply_dns("cloudflare")
    ops.apply_strategy("alt")
    monkeypatch.setattr(api.dns, "restore_adapter", lambda *a: (_ for _ in ()).throw(RuntimeError("adapter gone")))
    with pytest.raises(RuntimeError, match="adapter gone"):
        ops.restore(before)
    assert api.winws.state()["current"] == "general"   # остальное всё равно вернулось


def test_tampered_hosts_block_in_the_record_is_refused(env):
    ops, _, _ = env
    before = ops.capture()
    before["hosts"]["block"] = "0.0.0.0 bank.example\r\n"
    with pytest.raises(ChimeraError):
        ops.restore(before)


def test_candidates_come_from_the_modules(env):
    ops, _, _ = env
    ops.capture()
    assert ops.strategies() == ["general", "alt"]
    assert ops.dns_providers(unblock=False) == ["cloudflare"] and ops.dns_providers(unblock=True) == ["comss"]
    assert "malw" in ops.hosts_providers() and "flowseal-hosts" not in ops.hosts_providers()
    assert ops.proxy_available() and ops.dns_available()
