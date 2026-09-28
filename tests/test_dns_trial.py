"""Смена DNS с автооткатом: применили, N секунд на «оставить», иначе вернулось как было.

Таймер и время подменены (управляются из теста), PowerShell — заглушка, которая пишет
команды. Откат должен вернуть именно прежнее состояние адаптера: DHCP или статические серверы."""

import pytest

from modules.dns_jumper import manager as dns_manager
from ui import api as api_mod


class FakeTimer:
    def __init__(self, seconds, fn):
        self.seconds, self.fn, self.cancelled = seconds, fn, False

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.fn()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(dns_manager, "CHANGED_PATH", tmp_path / "dns_changed.json")
    cmds = []
    monkeypatch.setattr(dns_manager, "_ps", lambda cmd: cmds.append(cmd) or "")
    j = dns_manager.DnsJumper()
    timers = []
    clock = {"now": 1000.0}
    monkeypatch.setattr(j, "_now", lambda: clock["now"])
    monkeypatch.setattr(j, "_schedule", lambda seconds, fn: timers.append(FakeTimer(seconds, fn)) or timers[-1])
    monkeypatch.setattr(j, "get_provider",
                        lambda pid: {"id": pid, "name": pid.title(), "servers": ["1.1.1.1", "1.0.0.1"], "ipv6": [], "doh": ""})
    adapters = {3: {"index": 3, "name": "Ethernet", "dns": ["192.168.1.1"], "guid": "{AAA}"},
                7: {"index": 7, "name": "Wi-Fi", "dns": ["8.8.8.8"], "guid": "{BBB}"}}
    monkeypatch.setattr(j, "adapters", lambda: list(adapters.values()))
    static = {"{AAA}": False, "{BBB}": True}
    monkeypatch.setattr(j, "_is_static", lambda guid: static.get(guid))
    return j, cmds, timers, clock, adapters


def restore_cmds(cmds):
    return [c for c in cmds if "ResetServerAddresses" in c or "-ServerAddresses '8.8.8.8'" in c]


def test_trial_applies_dns_and_arms_a_timer(env):
    j, cmds, timers, clock, _ = env
    res = j.set_dns_trial(3, "cloudflare", seconds=15)

    assert any("-ServerAddresses '1.1.1.1','1.0.0.1'" in c for c in cmds)
    assert timers[-1].seconds == 15
    assert res["trial"]["deadline"] == 1015.0
    assert res["trial"]["adapter"] == 3
    assert res["trial"]["previous"] == {"dns": ["192.168.1.1"], "static": False}


def test_timeout_returns_dhcp_adapter_to_dhcp(env):
    j, cmds, timers, _, _ = env
    j.set_dns_trial(3, "cloudflare")
    cmds.clear()

    timers[-1].fire()

    assert any("-InterfaceIndex 3 -ResetServerAddresses" in c for c in cmds)
    assert j.trials() == []
    assert j.changed_adapters() == []


def test_timeout_returns_static_adapter_to_its_previous_servers(env):
    j, cmds, timers, _, _ = env
    j.set_dns_trial(7, "cloudflare")
    cmds.clear()

    timers[-1].fire()

    assert any("-InterfaceIndex 7 -ServerAddresses '8.8.8.8'" in c for c in cmds)
    assert not any("ResetServerAddresses" in c for c in cmds)
    # DNS 8.8.8.8 выставил не мы — адаптер после отката снова «не наш»
    assert j.changed_adapters() == []


def test_confirm_keeps_new_dns_and_cancels_the_timer(env):
    j, cmds, timers, _, _ = env
    j.set_dns_trial(3, "cloudflare")
    cmds.clear()

    j.trial_confirm(3)
    timers[-1].fire()  # отменённый таймер ничего не делает

    assert timers[-1].cancelled
    assert cmds == []
    assert j.trials() == []
    assert j.changed_adapters() == [3]


def test_manual_revert_does_the_same_as_timeout(env):
    j, cmds, timers, _, _ = env
    j.set_dns_trial(3, "cloudflare")
    cmds.clear()

    j.trial_revert(3)

    assert any("-InterfaceIndex 3 -ResetServerAddresses" in c for c in cmds)
    assert timers[-1].cancelled
    assert j.trials() == []


def test_revert_is_idempotent(env):
    j, cmds, timers, _, _ = env
    j.set_dns_trial(3, "cloudflare")
    j.trial_revert(3)
    cmds.clear()

    j.trial_revert(3)
    timers[-1].fire()

    assert cmds == []


def test_state_reports_deadline_and_previous(env):
    j, _, _, clock, _ = env
    j.set_dns_trial(3, "cloudflare", seconds=20)
    clock["now"] = 1012.0

    t = j.trials()[0]

    assert t["adapter"] == 3 and t["provider"] == "cloudflare"
    assert t["deadline"] == 1020.0 and t["seconds_left"] == 8
    assert t["previous"] == {"dns": ["192.168.1.1"], "static": False}


def test_second_trial_on_same_adapter_keeps_the_original_previous(env):
    j, cmds, timers, _, adapters = env
    j.set_dns_trial(3, "cloudflare")
    first = timers[-1]
    adapters[3]["dns"] = ["1.1.1.1", "1.0.0.1"]  # теперь на адаптере уже наш пробный DNS

    j.set_dns_trial(3, "google")

    assert first.cancelled
    assert j.trials()[0]["previous"] == {"dns": ["192.168.1.1"], "static": False}


def test_failed_apply_arms_nothing(env, monkeypatch):
    j, cmds, timers, _, _ = env

    def boom(cmd):
        raise RuntimeError("отказано в доступе")
    monkeypatch.setattr(dns_manager, "_ps", boom)

    with pytest.raises(RuntimeError):
        j.set_dns_trial(3, "cloudflare")

    assert timers == [] and j.trials() == []


def test_unknown_static_flag_falls_back_to_dhcp(env, monkeypatch):
    j, cmds, timers, _, _ = env
    monkeypatch.setattr(j, "_is_static", lambda guid: None)
    j.set_dns_trial(3, "cloudflare")
    cmds.clear()

    timers[-1].fire()

    assert any("ResetServerAddresses" in c for c in cmds)


def test_seconds_are_bounded(env):
    j, _, timers, _, _ = env
    j.set_dns_trial(3, "cloudflare", seconds=0)
    assert 5 <= timers[-1].seconds <= 120
    j.set_dns_trial(3, "cloudflare", seconds=10_000)
    assert timers[-1].seconds <= 120


# --- Api ---------------------------------------------------------------------------------

@pytest.fixture
def api(env, monkeypatch):
    j = env[0]
    a = api_mod.Api.__new__(api_mod.Api)
    a.dns = j
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    return a


def test_api_trial_needs_admin(api, monkeypatch):
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    res = api.dns_set_trial(3, "cloudflare")
    assert res["ok"] is False and "администратор" in res["error"]


def test_api_trial_flow(api):
    res = api.dns_set_trial(3, "cloudflare", 15)
    assert res["ok"] and res["data"]["trial"]["adapter"] == 3
    assert api.dns_trial_confirm(3)["ok"]
    assert api.dns.trials() == []


def test_api_trial_revert(api):
    api.dns_set_trial(3, "cloudflare", 15)
    assert api.dns_trial_revert(3)["ok"]
    assert api.dns.trials() == []


def test_dns_state_carries_trial(api, monkeypatch):
    monkeypatch.setattr(api.dns, "list_providers", lambda: [])
    api.dns_set_trial(3, "cloudflare", 15)
    data = api.dns_state()["data"]
    assert data["trial"]["adapter"] == 3
    assert data["trials"][0]["adapter"] == 3
    api.dns_trial_confirm(3)
    assert api.dns_state()["data"]["trial"] is None


def test_old_dns_set_is_untouched(api):
    res = api.dns_set(3, "cloudflare")
    assert res["ok"] and "trial" not in res["data"]
