"""Что пробовать при подборе: способы и исключённые варианты из настроек — или на один запуск.

Человек знает, что DNS у него не поможет или прокси режет скорость, — и не ждёт перебора там,
где перспективы нет. Самолечение подбирает теми же способами.
"""

import threading

import pytest

from modules import appconfig
from modules.autotune.engine import Engine
from modules.autotune.manager import AutotuneManager
from modules.errors import ChimeraError
from tests.autotune_net import FakeOps, blocked_unless
from ui import api as api_mod


def network():
    # YouTube открывает только alt2 или hosts comss — смотрим, до чего дойдёт подбор
    return FakeOps({"youtube": ["youtube.com"]},
                   {"youtube.com": blocked_unless(lambda s: s["strategy"] == "alt2" or s["hosts"].get("youtube") == "comss")},
                   strategies=("general", "alt", "alt2"), hosts=("xbox", "comss"), dns_plain=("cloudflare",),
                   dns_unblock=("comss-dns",))


def applied(ops, name):
    return [c[1] for c in ops.calls if c[0] == name]


def test_only_the_chosen_methods_are_tried():
    ops = network()
    Engine(ops, allowed=("hosts",)).run(["youtube"])
    assert applied(ops, "apply_strategy") == [] and applied(ops, "apply_dns") == []
    assert ops.state["hosts"]["youtube"] == "comss"


def test_excluded_options_are_never_tried():
    ops = network()
    Engine(ops, exclude={"strategy": ["alt2", "alt"], "hosts": ["comss"]}).run(["youtube"])
    assert "alt2" not in applied(ops, "apply_strategy") and "alt" not in applied(ops, "apply_strategy")
    assert all(call[2] != "comss" for call in ops.calls if call[0] == "assign_hosts")


def test_a_remembered_option_that_was_excluded_later_is_not_tried_first_either():
    ops = network()
    Engine(ops, memory={"youtube": {"kind": "strategy", "id": "alt2"}}, exclude={"strategy": ["alt2"]}).run(["youtube"])
    assert "alt2" not in applied(ops, "apply_strategy")


@pytest.fixture
def make(tmp_path):
    def build(settings=None):
        ops = network()
        mgr = AutotuneManager(ops, tmp_path / "autotune.json", threading.RLock(), memory_path=tmp_path / "memory.json",
                              worker=lambda fn: fn(), settings=lambda: settings or {})
        return mgr, ops
    return build


def test_the_settings_decide_the_methods_and_the_session_shows_them(make):
    mgr, ops = make({"steps": ["hosts", "strategy"], "exclude": {"strategy": ["alt2"]}})
    active = mgr.start()["active"]
    assert active["steps"] == ["strategy", "hosts"]
    assert "alt2" not in applied(ops, "apply_strategy") and ops.state["hosts"]["youtube"] == "comss"


def test_one_run_can_narrow_the_methods_without_touching_the_settings(make):
    mgr, ops = make({"steps": ["strategy", "hosts", "dns", "proxy"]})
    assert mgr.start(steps=["strategy"])["active"]["steps"] == ["strategy"]
    assert ops.state["strategy"] == "alt2" and applied(ops, "assign_hosts") == []


@pytest.mark.parametrize("steps", [[], ["vpn"], "strategy"])
def test_unknown_or_empty_methods_are_refused_before_anything_changes(make, steps):
    mgr, ops = make()
    with pytest.raises(ChimeraError):
        mgr.start(steps=steps)
    assert ops.calls == [] and mgr.active is None


def test_methods_are_kept_in_their_own_order_and_checked():
    assert appconfig._autotune_steps(["proxy", "strategy"]) == ["strategy", "proxy"]
    for bad in ([], ["vpn"], ["dns", "dns"], "dns"):
        with pytest.raises(ValueError):
            appconfig._autotune_steps(bad)


def test_exclusions_are_checked_and_empty_ones_dropped():
    assert appconfig._autotune_exclude({"dns": ["google", "google"], "hosts": []}) == {"dns": ["google"]}
    for bad in ({"proxy": ["proxy"]}, {"dns": "google"}, {"dns": [""]}, ["dns"]):
        with pytest.raises(ValueError):
            appconfig._autotune_exclude(bad)


def test_the_method_list_names_every_option(monkeypatch):
    a = api_mod.Api.__new__(api_mod.Api)
    ops = network()
    a._autotune = type("Autotune", (), {"ops": ops})()
    a.winws = type("Winws", (), {"strategies": lambda self: [{"id": "alt2", "name": "ALT2"}]})()
    a.hosts = type("Hosts", (), {"providers": lambda self: [{"id": "comss", "name": "Comss DNS"}]})()
    a.dns = type("Dns", (), {"list_providers": lambda self: [{"id": "cloudflare", "name": "Cloudflare"}]})()
    monkeypatch.setattr(api_mod.appconfig, "load", lambda: {"autotune_steps": ["strategy"], "autotune_exclude": {"dns": ["x"]}})
    data = a.autotune_methods()["data"]
    assert data["enabled"] == ["strategy"] and data["exclude"] == {"dns": ["x"]}
    assert {"id": "alt2", "name": "ALT2"} in data["candidates"]["strategy"]
    assert {"id": "comss", "name": "Comss DNS"} in data["candidates"]["hosts"]
    assert [r["id"] for r in data["candidates"]["dns"]] == ["cloudflare", "comss-dns"]
