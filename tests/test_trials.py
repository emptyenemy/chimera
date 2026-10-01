"""Пробы проверяются без процессов, системных изменений, сети и ожидания таймеров."""

import json
import threading
from types import SimpleNamespace

import pytest

from modules.errors import ChimeraError
from modules.trials import TrialManager
from ui.api import Api


class Ops:
    def __init__(self):
        self.value = "original"
        self.applied = self.restored = 0
        self.fail_apply = self.fail_restore = False
        self.status = "ok"

    def capture(self, kind, target):
        return {"private": self.value}

    def apply(self, kind, target):
        self.applied += 1
        self.value = target
        if self.fail_apply:
            raise RuntimeError("private diagnostic")

    def restore(self, kind, before):
        self.restored += 1
        if self.fail_restore:
            raise RuntimeError("private diagnostic")
        self.value = before["private"]

    def check(self, domain):
        return {"status": self.status, "ms": 12, "private": "private diagnostic"}


@pytest.fixture
def trial(tmp_path):
    ops, clock, workers, timers, changes = Ops(), [0.0], [], [], []

    def schedule(seconds, callback):
        timer = SimpleNamespace(callback=callback, cancel=lambda: None)
        timers.append(timer)
        return timer

    manager = TrialManager(ops, tmp_path / "trial.json", threading.RLock(), now=lambda: clock[0],
                           schedule=schedule, worker=workers.append, changed=lambda: changes.append(manager.state()))
    return SimpleNamespace(manager=manager, ops=ops, clock=clock, workers=workers, timers=timers, changes=changes)


def start(trial, kind="strategy", target="new"):
    state = trial.manager.start(kind, target)
    return state["active"]["id"]


def test_checks_then_confirmation_keeps_settings_and_stale_timer_cannot_revert(trial):
    tid = start(trial)
    with pytest.raises(ChimeraError, match="Дождитесь"):
        trial.manager.confirm(tid)
    trial.workers.pop()()
    state = trial.manager.confirm(tid)
    assert state["active"] is None and state["last"]["phase"] == "confirmed"
    trial.timers[0].callback()
    assert trial.ops.value == "new" and trial.ops.restored == 0
    assert not trial.manager.path.exists()
    assert "private" not in json.dumps(state)


def test_timeout_reverts_without_client_and_restores_runtime_snapshot(trial):
    start(trial)
    assert trial.manager.path.exists()
    trial.clock[0] = 60
    trial.timers[0].callback()
    assert trial.ops.value == "original"
    assert trial.manager.state()["last"]["reason"] == "timeout"
    trial.workers.pop()()
    assert trial.manager.state()["active"] is None


def test_deadline_cannot_be_confirmed_before_delayed_timer_runs(trial):
    tid = start(trial)
    trial.workers.pop()()
    trial.clock[0] = 60
    with pytest.raises(ChimeraError):
        trial.manager.confirm(tid)
    assert trial.ops.value == "original"


@pytest.mark.parametrize("status", ["blocked", "dns_error", "error", "http_error"])
def test_failed_control_site_rolls_back_and_reports_checks(trial, status):
    trial.ops.status = status
    start(trial)
    trial.workers.pop()()
    state = trial.manager.state()
    assert state["active"] is None and state["last"]["reason"] == "check_failed"
    assert state["last"]["checks"][0]["status"] == status
    assert trial.ops.value == "original"


def test_challenge_is_a_successful_browser_reachability_check(trial):
    trial.ops.status = "challenge"
    tid = start(trial)
    trial.workers.pop()()
    trial.manager.confirm(tid)
    assert trial.ops.value == "new"


def test_partial_apply_error_rolls_back_and_does_not_leak_diagnostics(trial):
    trial.ops.fail_apply = True
    with pytest.raises(ChimeraError) as error:
        start(trial)
    assert error.value.code == "err.trial.apply"
    assert trial.ops.value == "original" and not trial.manager.path.exists()


def test_failed_rollback_keeps_recovery_data_and_can_be_retried(trial):
    tid = start(trial)
    trial.ops.fail_restore = True
    result = trial.manager.revert(tid)
    assert result["active"]["phase"] == "rollback_failed" and trial.manager.path.exists()
    assert "private" not in json.dumps(result)
    with pytest.raises(ChimeraError):
        start(trial)
    trial.ops.fail_restore = False
    trial.manager.revert(tid)
    assert trial.ops.value == "original" and not trial.manager.path.exists()


def test_failed_initial_save_never_applies_settings(trial, monkeypatch):
    monkeypatch.setattr(trial.manager, "_save", lambda: (_ for _ in ()).throw(OSError("denied")))
    with pytest.raises(ChimeraError) as error:
        start(trial)
    assert error.value.code == "err.trial.save"
    assert trial.ops.applied == 0 and trial.manager.active is None


def test_second_trial_and_stale_client_ids_do_not_replace_original_snapshot(trial):
    tid = start(trial)
    before = trial.manager.path.read_bytes()
    with pytest.raises(ChimeraError):
        start(trial, target="another")
    with pytest.raises(ChimeraError):
        trial.manager.revert("0000000000000000")
    assert trial.manager.path.read_bytes() == before
    trial.manager.revert(tid)
    newer = start(trial, target="another")
    trial.timers[0].callback()
    trial.workers[0]()
    assert trial.manager.state()["active"]["id"] == newer


def test_panic_cancels_trial_without_reenabling_anything(trial):
    start(trial)
    trial.manager.abandon()
    trial.ops.value = "off"
    trial.timers[0].callback()
    trial.workers.pop()()
    assert trial.ops.value == "off" and trial.ops.restored == 0


def test_interrupted_trial_is_restored_on_next_owner_start(trial):
    start(trial)
    restarted = TrialManager(trial.ops, trial.manager.path, threading.RLock())
    assert restarted.state()["active"]["phase"] == "interrupted"
    restarted.recover()
    assert trial.ops.value == "original" and restarted.active is None


def test_corrupt_recovery_record_is_visible_and_blocks_changes(trial):
    trial.manager.path.write_text("invalid", encoding="utf-8")
    restarted = TrialManager(trial.ops, trial.manager.path, threading.RLock())
    assert restarted.state()["active"]["phase"] == "invalid"
    with pytest.raises(ChimeraError):
        restarted.start("strategy", "new")
    assert trial.ops.applied == 0


@pytest.mark.parametrize("seconds", [True, "60", 14, 301, 60.5])
def test_invalid_time_changes_nothing(trial, seconds):
    with pytest.raises(ChimeraError):
        trial.manager.start("strategy", "new", seconds)
    assert trial.ops.applied == 0


@pytest.mark.parametrize("domains", [[], "example.com", ["https://example.com"], ["example.com/path"], ["example.com:443"], [1], ["a.com"] * 7])
def test_invalid_control_domains_change_nothing(trial, domains):
    with pytest.raises(ChimeraError):
        trial.manager.start("strategy", "new", domains=domains)
    assert trial.ops.applied == 0


def test_dispatch_blocks_mutations_but_allows_reads_and_revert(trial):
    api = Api.__new__(Api)
    api._service_owned = True
    api._trial = trial.manager
    api.hub = SimpleNamespace(poke=lambda *args: None)
    stopped = []
    api.proxy = SimpleNamespace(stop=lambda: stopped.append(True), state=lambda: {"running": True})
    tid = start(trial)
    result = json.loads(api.dispatch("proxy_stop", "[]"))
    assert result["code"] == "err.trial.busy" and not stopped
    assert json.loads(api.dispatch("proxy_state", "[]"))["ok"]
    assert json.loads(api.dispatch("trial_revert", json.dumps([tid])))["ok"]


def test_service_owner_gets_all_trial_requests(trial, monkeypatch):
    from ui import api as api_mod
    from modules.cli import client
    api = Api.__new__(Api)
    api._service_owned = False
    api._trial = trial.manager
    calls = []
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    monkeypatch.setattr(client, "connect", lambda: SimpleNamespace(api=lambda method, *args: calls.append((method, args)) or {"active": None, "last": None}))
    api.proxy = SimpleNamespace(_load=lambda: {})
    api.winws = SimpleNamespace(_load=lambda: {})
    api.tg = SimpleNamespace(config={})
    assert api.trial_state()["ok"]
    assert api.trial_start("strategy", "new")["ok"]
    assert api.trial_confirm("id")["ok"]
    assert api.trial_revert("id")["ok"]
    assert [method for method, _ in calls] == ["trial_state", "trial_start", "trial_confirm", "trial_revert"]
    assert trial.ops.applied == 0


def test_panic_leaves_a_cancelled_record_if_unlink_is_blocked(trial, monkeypatch):
    from pathlib import Path

    start(trial)
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == trial.manager.path:
            raise PermissionError("locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    trial.manager.abandon()
    trial.timers[0].callback()
    recovered = TrialManager(trial.ops, trial.manager.path, threading.RLock())
    recovered.recover()
    assert recovered.active is None
    assert trial.ops.restored == 0


def test_panic_still_stops_modules_when_trial_record_cannot_be_cleared(trial, monkeypatch):
    from pathlib import Path

    start(trial)
    monkeypatch.setattr(trial.manager, "_save", lambda: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    stopped = []
    api = Api.__new__(Api)
    api._trial = trial.manager
    api.winws = api.proxy = api.tg = SimpleNamespace(stop=lambda: stopped.append(True))
    api.hosts = SimpleNamespace(set_enabled=lambda value: stopped.append(value))
    api.dns = SimpleNamespace(changed_adapters=lambda: [])
    monkeypatch.setattr("ui.api.is_admin", lambda: True)
    monkeypatch.setattr("ui.api.service.is_running", lambda: False)
    result = api.panic_all()["data"]
    assert result["failed"] == 1 and result["steps"][0]["step"] == "trial"
    assert stopped == [True, True, True, False]
    assert trial.manager.state()["active"] is None
    trial.manager.recover()
    trial.timers[0].callback()
    assert trial.ops.restored == 0
