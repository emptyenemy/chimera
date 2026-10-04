"""Автонастройка внутри Api: блокировка изменений, «Выключить всё», служба и правки списков."""

import json
from types import SimpleNamespace

import pytest

from modules.autotune.manager import AutotuneManager
from modules.cli import client
from tests.autotune_net import FakeOps, blocked_unless
from ui import api as api_mod
from ui.api import Api


def network():
    return FakeOps({"youtube": ["youtube.com"]}, {"youtube.com": blocked_unless(lambda s: s["strategy"] == "alt")},
                   hosts=(), dns_plain=(), dns_unblock=())


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    a = Api.__new__(Api)
    a._service_owned = True
    a.ops = network()
    pending = []
    a.pending = pending
    a._autotune = AutotuneManager(a.ops, tmp_path / "autotune.json", Api._mutation_lock,
                                  memory_path=tmp_path / "memory.json", worker=pending.append)
    a._trial = SimpleNamespace(active=None, state=lambda: {"active": None, "last": None})
    a.trial_state = lambda: {"ok": True, "data": {"active": None, "last": None}}
    a.hub = SimpleNamespace(poke=lambda *keys: None)
    return a


def call(api, method, *args):
    return json.loads(api.dispatch(method, json.dumps(list(args))))


def test_running_auto_setup_blocks_other_changes_but_not_reads_or_cancel(api):
    stopped = []
    api.proxy = SimpleNamespace(stop=lambda: stopped.append(True), state=lambda: {"running": False})
    assert call(api, "autotune_start")["ok"]
    assert call(api, "proxy_stop")["code"] == "err.autotune.busy" and not stopped
    assert call(api, "proxy_state")["ok"] and call(api, "autotune_state")["data"]["active"]["phase"] == "running"
    assert call(api, "autotune_start")["code"] == "err.autotune.busy"
    assert call(api, "autotune_cancel")["ok"]
    api.pending[0]()   # поток подбора видит отмену и откатывает
    assert call(api, "autotune_state")["data"]["last"]["phase"] == "cancelled"
    assert call(api, "proxy_stop")["ok"] and stopped == [True]


def test_finished_result_does_not_block_changes(api):
    api.proxy = SimpleNamespace(stop=lambda: None, state=lambda: {"running": False})
    call(api, "autotune_start")
    api.pending[0]()
    assert call(api, "autotune_state")["data"]["active"]["phase"] == "done"
    assert call(api, "proxy_stop")["ok"] and call(api, "autotune_revert")["ok"]


def test_trial_is_refused_while_auto_setup_runs(api):
    call(api, "autotune_start")
    assert call(api, "trial_start", "strategy", "alt")["code"] == "err.autotune.busy"


def test_panic_closes_auto_setup_without_rollback(api, monkeypatch):
    stopped = []
    api.winws = api.proxy = api.tg = SimpleNamespace(stop=lambda: stopped.append(True))
    api.hosts = SimpleNamespace(set_enabled=lambda value: stopped.append(value))
    api.dns = SimpleNamespace(changed_adapters=lambda: [])
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    call(api, "autotune_start")
    result = api.panic_all()["data"]
    assert result["steps"][0] == {"step": "autotune", "ok": True}
    assert api.ops.restored == [] and api._autotune.state()["last"]["reason"] == "panic"
    api.pending[0]()   # опоздавший поток подбора ничего не включает обратно
    assert api.ops.applied("apply_strategy") == []


def test_list_edit_during_search_waits_for_the_end(api, monkeypatch):
    applied = []
    monkeypatch.setattr(api_mod.liveapply, "apply_event", lambda kind, name, *mods: applied.append((kind, name)) or [])
    api.winws = api.proxy = api.hosts = None
    call(api, "autotune_start")
    errors = api._lists_file_changed("changed", "youtube")
    assert errors[0]["module"] == "autotune" and applied == []
    api._autotune.changed = api._autotune_changed
    api.pending[0]()
    assert applied == [("changed", "youtube")]


def test_window_forwards_auto_setup_to_the_running_service(api, monkeypatch):
    api._service_owned = False
    calls = []
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    monkeypatch.setattr(client, "connect", lambda: SimpleNamespace(
        api=lambda method, *args: calls.append((method, args)) or {"active": None, "last": None}))
    api.proxy = SimpleNamespace(_load=lambda: {})
    api.winws = SimpleNamespace(_load=lambda: {})
    api.tg = SimpleNamespace(config={})
    for method, args in (("autotune_state", ()), ("autotune_diagnose", (["youtube"],)), ("autotune_start", (None, "smart")),
                         ("autotune_cancel", ()), ("autotune_revert", ()), ("autotune_keep", ())):
        assert getattr(api, method)(*args)["ok"]
    assert [c[0] for c in calls] == ["autotune_state", "autotune_diagnose", "autotune_start",
                                     "autotune_cancel", "autotune_revert", "autotune_keep"]
    assert api.ops.calls == []


def test_catalog_and_diagnose_are_reads(api):
    assert Api.is_read("autotune_state") and Api.is_read("autotune_catalog") and Api.is_read("autotune_diagnose")
    assert not Api.is_read("autotune_start") and not Api.is_read("autotune_cancel")
    assert call(api, "autotune_catalog")["data"] == [{"name": "youtube", "targets": ["youtube.com"]}]
