import json
import threading

import pytest

from modules import configbackups
from modules.errors import ChimeraError
from modules.trials import TrialManager
from tests.test_configbackups import live as live
from ui.trials import TrialOps


@pytest.mark.parametrize("running", [True, False])
def test_strategy_rollback_restores_selection_and_running_state(live, running):
    api = live.api
    api.winws.flag = running
    api.winws.state = lambda: {"running": api.winws.flag, "current": api.winws._current, "external": False}
    ops = TrialOps(api)
    before = ops.capture("strategy", "alt")
    ops.apply("strategy", "alt")
    assert api.winws.flag and api.winws._current == "alt"
    ops.restore("strategy", before)
    assert api.winws.flag == running and api.winws.config["last_strategy"] == "general"
    if running:
        assert api.winws._current == "general"
    assert configbackups.list_backups()[0]["kind"] == "auto"


@pytest.mark.parametrize("running", [True, False])
def test_tun_rollback_returns_previous_mode_and_running_state(live, running):
    api = live.api
    api.proxy.flag = running
    ops = TrialOps(api)
    before = ops.capture("tun", "tun")
    ops.apply("tun", "tun")
    assert api.proxy.config["mode"] == "tun" and api.proxy.flag
    ops.restore("tun", before)
    assert api.proxy.config["mode"] == "pac" and api.proxy.flag == running


def test_hosts_rollback_preserves_exact_block_and_unrelated_edits(live, monkeypatch):
    hosts = live.api.hosts
    old = "# original\r\n127.0.0.1 localhost\r\n\r\n# >>> chimera-hosts >>>\r\n1.2.3.4 example.com\r\n# <<< chimera-hosts <<<\r\n"
    hosts.hosts_path.write_bytes(old.encode())
    hosts._save_state({"enabled": True, "assignments": {"comss": ["discord"]}, "entries": [{"host": "example.com", "ip": "1.2.3.4"}]})
    monkeypatch.setattr(hosts, "_write_hosts", lambda text: hosts.hosts_path.write_bytes(text.encode()))
    ops = TrialOps(live.api)
    before = ops.capture("hosts", "off")
    # Другой инструмент изменил свою строку во время пробы.
    hosts.hosts_path.write_bytes(b"# original\r\n127.0.0.1 localhost\r\n# third-party edit\r\n")
    hosts._save_state({"enabled": False, "assignments": {}, "entries": []})
    ops.restore("hosts", before)
    actual = hosts.hosts_path.read_bytes()
    assert b"# third-party edit\r\n" in actual
    assert b"# >>> chimera-hosts >>>\r\n1.2.3.4 example.com\r\n# <<< chimera-hosts <<<\r\n" in actual
    assert hosts._load_state() == before["state"]


def test_hosts_rollback_removes_only_trial_block_when_initially_disabled(live, monkeypatch):
    hosts = live.api.hosts
    hosts.hosts_path.write_bytes(b"127.0.0.1 localhost\r\n")
    monkeypatch.setattr(hosts, "_write_hosts", lambda text: hosts.hosts_path.write_bytes(text.encode()))
    ops = TrialOps(live.api)
    before = ops.capture("hosts", "on")
    hosts.hosts_path.write_bytes(b"127.0.0.1 localhost\r\n# other\r\n# >>> chimera-hosts >>>\r\n1.2.3.4 example.com\r\n# <<< chimera-hosts <<<\r\n")
    ops.restore("hosts", before)
    assert hosts.hosts_path.read_bytes() == b"127.0.0.1 localhost\r\n# other\r\n"


def test_external_strategy_is_refused_before_snapshot_or_system_changes(live):
    live.api.winws.state = lambda: {"external": True, "running": True}
    with pytest.raises(ChimeraError):
        TrialOps(live.api).capture("strategy", "alt")
    assert not configbackups.list_backups()


def test_recovery_cannot_stop_unknown_external_process(live):
    live.api.proxy.state = lambda: {"external": True, "running": True}
    before = list(live.events)
    with pytest.raises(ChimeraError):
        TrialOps(live.api).restore("tun", {"running": False, "mode": "pac"})
    assert live.events == before


def test_snapshot_restore_recovers_from_failed_trial_without_blocking_setters(live):
    api = live.api
    api._trial = TrialManager(TrialOps(api), live.data / "trial.json", threading.RLock(), worker=lambda fn: None)
    snapshot = configbackups.create_snapshot(live.ops.backup_state(("proxy",), ()))
    api._trial.start("tun", "tun")
    api._trial.active["phase"] = "rollback_failed"
    result = json.loads(api.dispatch("config_backup_restore", json.dumps([snapshot, True])))
    assert result["ok"] and not result["data"]["errors"]
    assert api._trial.active is None and api.proxy.config["mode"] == "pac"
