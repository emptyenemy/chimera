"""Обновление данных внутри Api: снимок до записи, применение списков, перезапуск стратегии."""

from types import SimpleNamespace

import pytest

from ui import api as api_mod
from ui.api import Api


class FakeUpdater:
    result = {}

    def __init__(self, *args, **kwargs):
        pass

    def install(self, before=None):
        before(self.result["added"] + self.result["updated"])
        return dict(self.result)

    def check(self):
        return {"current": "2026.10.01", "latest": "2026.10.05", "update": True}


@pytest.fixture
def api(monkeypatch):
    a = Api.__new__(Api)
    a._service_owned = True
    a.log = []
    a.winws = SimpleNamespace(running=True, _ours_alive=True, _current="general", config={"last_strategy": "general"},
                              start=lambda sid: a.log.append(("restart", sid)))
    a.proxy = a.hosts = None
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    monkeypatch.setattr(api_mod.dataupdate, "DataUpdater", FakeUpdater)
    monkeypatch.setattr(api_mod.configbackups, "create_snapshot", lambda snap, kind: a.log.append(("snapshot", sorted(snap["lists"]))))
    monkeypatch.setattr(api_mod.ShareOps, "backup_state", lambda self, sections, lists: {"states": {}, "lists": {n: "" for n in lists}})
    monkeypatch.setattr(api_mod.domains, "available_lists", lambda: ["youtube", "new"])
    monkeypatch.setattr(api_mod.liveapply, "lists_changed", lambda names, *mods: a.log.append(("apply", names)) or [])
    return a


def test_changed_lists_are_snapshotted_first_and_applied_after(api):
    FakeUpdater.result = {"version": "2026.10.05", "added": ["lists/new.txt"], "updated": ["lists/youtube.txt"], "kept": []}
    res = api.data_update()["data"]
    assert api.log == [("snapshot", ["new", "youtube"]), ("apply", ["new", "youtube"])]
    assert res["restarted"] is False


def test_changed_strategy_files_restart_the_running_strategy(api):
    FakeUpdater.result = {"version": "2026.10.05", "added": [], "updated": ["strategies/general.txt"], "kept": []}
    res = api.data_update()["data"]
    assert ("restart", "general") in api.log and res["restarted"] is True


@pytest.mark.parametrize("rel", ["strategies/hostlists/list-general.txt", "strategies/provider-map.json"])
def test_files_winws_rereads_or_never_reads_need_no_restart(api, rel):
    FakeUpdater.result = {"version": "2026.10.05", "added": [], "updated": [rel], "kept": []}
    assert api.data_update()["data"]["restarted"] is False and not [e for e in api.log if e[0] == "restart"]


def test_without_rights_the_update_lands_but_the_restart_is_reported(api, monkeypatch):
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    FakeUpdater.result = {"version": "2026.10.05", "added": [], "updated": ["strategies/alt.txt"], "kept": []}
    res = api.data_update()["data"]
    assert res["restarted"] is False and res["restart_error"]


def test_check_is_a_read_and_update_is_a_change():
    assert Api.is_read("data_check") and not Api.is_read("data_update")
