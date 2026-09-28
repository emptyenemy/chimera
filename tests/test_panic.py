"""«Выключить всё»: Api.panic_all() гасит всё независимо — ошибка одного шага не мешает
остальным; учёт адаптеров, где мы меняли DNS; очистка хвостов системного прокси при старте.

Api создаём через __new__ (настоящий поднимает менеджеры и потоки), модули — заглушки."""

import json

import pytest

from modules.dns_jumper import manager as dns_manager
from modules.proxy import manager as proxy_manager
from ui import api as api_mod


class Module:
    """Заглушка менеджера: пишет вызовы; fail — исключение на нужном методе."""

    def __init__(self, name, log, fail=None):
        self.name, self.log, self.fail = name, log, fail

    def _call(self, what, *args):
        self.log.append((self.name, what, *args))
        if self.fail == what:
            raise RuntimeError(f"{self.name}: сбой")
        return {"ok": True}

    def stop(self): return self._call("stop")
    def set_enabled(self, value): return self._call("set_enabled", value)


class FakeDns:
    def __init__(self, log, changed=(), fail=None):
        self.log, self._changed, self.fail = log, list(changed), fail

    def changed_adapters(self):
        return list(self._changed)

    def reset_dns(self, idx):
        self.log.append(("dns", "reset", idx))
        if self.fail == idx:
            raise RuntimeError("адаптер недоступен")


@pytest.fixture
def api(monkeypatch):
    log = []
    a = api_mod.Api.__new__(api_mod.Api)
    a.winws, a.proxy, a.tg, a.hosts = (Module(n, log) for n in ("winws", "proxy", "tg", "hosts"))
    a.dns = FakeDns(log, changed=[3, 7])
    a.log = log
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    monkeypatch.setattr(api_mod.service, "send_stop", lambda: log.append(("service", "send_stop")))
    return a


def steps(res):
    return {s["step"]: s for s in res["data"]["steps"]}


def test_panic_stops_everything_and_reports_each_step(api):
    res = api.panic_all()

    assert res["ok"] is True
    assert [s["step"] for s in res["data"]["steps"]] == ["service", "winws", "proxy", "tg", "hosts", "dns"]
    assert all(s["ok"] for s in res["data"]["steps"])
    assert res["data"]["failed"] == 0
    assert ("winws", "stop") in api.log and ("proxy", "stop") in api.log and ("tg", "stop") in api.log
    assert ("hosts", "set_enabled", False) in api.log


def test_panic_resets_only_adapters_we_changed(api):
    api.panic_all()
    assert [c for c in api.log if c[0] == "dns"] == [("dns", "reset", 3), ("dns", "reset", 7)]


def test_one_failing_step_does_not_stop_the_rest(api):
    api.winws.fail = "stop"
    api.dns.fail = 3

    res = api.panic_all()
    got = steps(res)

    assert got["winws"]["ok"] is False and "сбой" in got["winws"]["error"]
    assert got["proxy"]["ok"] and got["tg"]["ok"] and got["hosts"]["ok"]
    assert got["dns"]["ok"] is False and "адаптер недоступен" in got["dns"]["error"]
    # после сбоя на адаптере 3 второй адаптер всё равно сброшен
    assert ("dns", "reset", 7) in api.log
    assert res["data"]["failed"] == 2


def test_without_admin_rights_only_privileged_steps_fail(api, monkeypatch):
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)

    got = steps(api.panic_all())

    assert got["hosts"]["ok"] is False and "администратор" in got["hosts"]["error"]
    assert got["dns"]["ok"] is False and "администратор" in got["dns"]["error"]
    assert got["winws"]["ok"] and got["proxy"]["ok"] and got["tg"]["ok"]
    assert ("hosts", "set_enabled", False) not in api.log


def test_running_service_is_asked_to_stop(api, monkeypatch):
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)

    got = steps(api.panic_all())

    assert ("service", "send_stop") in api.log
    assert got["service"]["ok"] is True


def test_stopped_service_is_not_touched(api):
    got = steps(api.panic_all())
    assert ("service", "send_stop") not in api.log
    assert got["service"]["ok"] is True


def test_panic_is_dispatchable_and_not_treated_as_a_read(api):
    # dispatch после записи дёргает хаб; «panic» — не чтение
    assert api_mod.Api.is_read("panic_all") is False


# --- учёт адаптеров, где мы меняли DNS ------------------------------------------------

@pytest.fixture
def jumper(tmp_path, monkeypatch):
    monkeypatch.setattr(dns_manager, "CHANGED_PATH", tmp_path / "dns_changed.json")
    calls = []
    monkeypatch.setattr(dns_manager, "_ps", lambda cmd: calls.append(cmd) or "")
    j = dns_manager.DnsJumper()
    monkeypatch.setattr(j, "get_provider", lambda pid: {"id": pid, "servers": ["1.1.1.1"], "ipv6": [], "doh": ""})
    return j, calls


def test_set_dns_remembers_adapter_and_reset_forgets_it(jumper):
    j, _ = jumper
    j.set_dns(3, "cloudflare")
    j.set_dns(7, "cloudflare")
    assert j.changed_adapters() == [3, 7]

    j.reset_dns(3)
    assert j.changed_adapters() == [7]


def test_changed_adapters_survive_restart(jumper, tmp_path):
    j, _ = jumper
    j.set_dns(5, "cloudflare")
    assert dns_manager.DnsJumper().changed_adapters() == [5]


def test_failed_set_dns_is_not_remembered(jumper, monkeypatch):
    j, _ = jumper

    def boom(cmd):
        raise RuntimeError("отказано в доступе")
    monkeypatch.setattr(dns_manager, "_ps", boom)
    with pytest.raises(RuntimeError):
        j.set_dns(9, "cloudflare")
    assert j.changed_adapters() == []


def test_broken_state_file_means_no_adapters(jumper):
    j, _ = jumper
    dns_manager.CHANGED_PATH.write_text("это не json", encoding="utf-8")
    assert j.changed_adapters() == []


# --- хвосты системного прокси после аварийного завершения -----------------------------

@pytest.fixture
def pm(monkeypatch):
    monkeypatch.setattr(proxy_manager.ProxyManager, "running", property(lambda self: False))
    monkeypatch.setattr(proxy_manager.ProxyManager, "_system_pids", staticmethod(lambda: []))
    return proxy_manager.ProxyManager()


def test_stale_pac_of_ours_is_removed_when_proxy_is_not_running(pm, monkeypatch):
    removed = []
    monkeypatch.setattr(pm, "_read_autoconfig_url", lambda: pm._pac_url())
    monkeypatch.setattr(pm, "_disable_system_proxy", lambda: removed.append(True))

    assert pm.cleanup_stale_system_proxy() is True
    assert removed == [True]


def test_foreign_pac_is_left_alone(pm, monkeypatch):
    monkeypatch.setattr(pm, "_read_autoconfig_url", lambda: "http://corp.example/proxy.pac")
    monkeypatch.setattr(pm, "_disable_system_proxy", lambda: pytest.fail("чужой PAC не трогаем"))
    assert pm.cleanup_stale_system_proxy() is False


def test_no_pac_means_nothing_to_clean(pm, monkeypatch):
    monkeypatch.setattr(pm, "_read_autoconfig_url", lambda: None)
    assert pm.cleanup_stale_system_proxy() is False


def test_pac_of_ours_stays_while_proxy_runs(pm, monkeypatch):
    monkeypatch.setattr(proxy_manager.ProxyManager, "running", property(lambda self: True))
    monkeypatch.setattr(pm, "_read_autoconfig_url", lambda: pm._pac_url())
    monkeypatch.setattr(pm, "_disable_system_proxy", lambda: pytest.fail("прокси работает"))
    assert pm.cleanup_stale_system_proxy() is False


def test_startup_cleanup_reports_to_log(api, monkeypatch):
    api.proxy.cleanup_stale_system_proxy = lambda: True
    written = []
    monkeypatch.setattr(api_mod.applog, "write", written.append)

    api._startup_cleanup()

    assert written and "PAC" in written[0]


def test_startup_cleanup_is_skipped_when_service_owns_the_modules(api, monkeypatch):
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    api.proxy.cleanup_stale_system_proxy = lambda: pytest.fail("прокси у службы")
    api._startup_cleanup()


def test_startup_cleanup_never_raises(api, monkeypatch):
    def boom():
        raise OSError("реестр недоступен")
    api.proxy.cleanup_stale_system_proxy = boom
    api._startup_cleanup()  # запуск программы из-за чистки хвостов падать не должен


def test_panic_result_is_json_serialisable(api):
    json.dumps(api.panic_all())
