"""Обновление программы в API (ui/updater.py): состояние, проверка, установка по кнопке."""

import pytest

from ui import updater as upd


@pytest.fixture
def cfg(monkeypatch):
    data = {"update_channel": "stable", "update_check": True}
    monkeypatch.setattr(upd.appconfig, "load", lambda: dict(data))
    return data


def _check_result(**kw):
    base = {"current": "0.1.0", "latest": "0.2.0", "update": True, "installable": True, "notes": "n",
            "url": "u", "asset": {"name": "Chimera-0.2.0-win64.zip", "url": "a", "size": 3, "sha256": "x"},
            "error": None}
    return {**base, **kw}


def test_snapshot_has_config_and_no_asset(cfg, monkeypatch):
    u = upd.Updater()
    monkeypatch.setattr(upd.selfupdate, "check", lambda channel, current: _check_result())
    u.check()
    s = u.snapshot()
    assert s["channel"] == "stable" and s["auto"] is True
    assert s["latest"] == "0.2.0" and s["update"] is True
    assert "asset" not in s  # ссылка и хеш — внутреннее дело, во фронт не нужны


def test_check_uses_channel_from_config(cfg, monkeypatch):
    cfg["update_channel"] = "beta"
    seen = []
    monkeypatch.setattr(upd.selfupdate, "check", lambda channel, current: seen.append(channel) or _check_result())
    upd.Updater().check()
    assert seen == ["beta"]


def test_install_from_sources_refuses(cfg, monkeypatch):
    monkeypatch.setattr(upd.paths, "IS_FROZEN", False)
    with pytest.raises(RuntimeError, match="git"):
        upd.Updater().install(shutdown=lambda: None, request_quit=lambda: None)


def test_install_without_found_update_refuses(cfg, monkeypatch):
    monkeypatch.setattr(upd.paths, "IS_FROZEN", True)
    with pytest.raises(RuntimeError, match="проверь"):
        upd.Updater().install(shutdown=lambda: None, request_quit=lambda: None)


def _frozen_with_update(monkeypatch, tmp_path, service_running=False):
    monkeypatch.setattr(upd.paths, "IS_FROZEN", True)
    monkeypatch.setattr(upd, "UPDATE_DIR", tmp_path)
    monkeypatch.setattr(upd.selfupdate, "check", lambda channel, current: _check_result())
    calls = []
    monkeypatch.setattr(upd.selfupdate, "download",
                        lambda asset, dest, progress=None: calls.append("download") or (progress(3, 3), dest / "a.zip")[1])
    monkeypatch.setattr(upd.selfupdate, "stage", lambda z, dest: calls.append("stage") or dest / "Chimera")
    monkeypatch.setattr(upd.selfupdate, "write_script",
                        lambda *a, **kw: calls.append(("script", kw["restart_service"], kw["relaunch"]))
                        or kw["script"])
    monkeypatch.setattr(upd.selfupdate, "launch", lambda script: calls.append("launch"))
    state = {"running": service_running}
    monkeypatch.setattr(upd.service, "is_running", lambda: state["running"])
    monkeypatch.setattr(upd.service, "send_stop", lambda: calls.append("service_stop") or state.update(running=False))
    return calls


def test_install_order_and_quit(cfg, monkeypatch, tmp_path):
    calls = _frozen_with_update(monkeypatch, tmp_path)
    u = upd.Updater()
    u.check()
    u.install(shutdown=lambda: calls.append("shutdown"), request_quit=lambda: calls.append("quit"))
    # сначала всё, что может упасть (скачать, распаковать, сохранить копию для отката),
    # и только потом гасим модули и уходим
    assert calls == ["download", "stage", ("script", False, True), "shutdown", "launch", "quit"]
    assert u.snapshot()["progress"] == 1.0


def test_install_backup_error_keeps_program_running(cfg, monkeypatch, tmp_path):
    calls = _frozen_with_update(monkeypatch, tmp_path)

    def broken(*a, **kw):
        raise RuntimeError("не удалось сохранить текущую версию для отката")
    monkeypatch.setattr(upd.selfupdate, "write_script", broken)
    u = upd.Updater()
    u.check()
    with pytest.raises(RuntimeError, match="отката"):
        u.install(shutdown=lambda: calls.append("shutdown"), request_quit=lambda: calls.append("quit"))
    assert "shutdown" not in calls and "quit" not in calls
    assert u.snapshot()["stage"] == "error"


def test_install_stops_service_and_restarts_it_after(cfg, monkeypatch, tmp_path):
    calls = _frozen_with_update(monkeypatch, tmp_path, service_running=True)
    u = upd.Updater()
    u.check()
    u.install(shutdown=lambda: calls.append("shutdown"), request_quit=lambda: calls.append("quit"))
    assert "service_stop" in calls
    assert ("script", True, True) in calls  # служба была — скрипт поднимет её обратно


def test_install_download_error_keeps_program_running(cfg, monkeypatch, tmp_path):
    calls = _frozen_with_update(monkeypatch, tmp_path)

    def broken(asset, dest, progress=None):
        raise RuntimeError("SHA256 не совпадает")
    monkeypatch.setattr(upd.selfupdate, "download", broken)
    u = upd.Updater()
    u.check()
    with pytest.raises(RuntimeError, match="SHA256"):
        u.install(shutdown=lambda: calls.append("shutdown"), request_quit=lambda: calls.append("quit"))
    assert "shutdown" not in calls and "quit" not in calls
    s = u.snapshot()
    assert s["stage"] == "error" and "SHA256" in s["error"]
