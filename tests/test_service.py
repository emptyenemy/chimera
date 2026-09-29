"""modules/service.py — задача планировщика (XML/dry-run), CLI и общая логика
автозапуска (autostart_modules), которую делят UI (Api._autostart_all) и
service-режим.

Ничего настоящего не трогаем: schtasks подменяем monkeypatch'ем subprocess.run
(и проверяем, что при --dry-run он вообще не зовётся), именованные объекты
синхронизации Windows (мьютекс/событие) — обёртки _open_mutex/_open_event/
_set_event подменяются напрямую, реальный kernel32 в тестах не участвует.
"""

from types import SimpleNamespace

import pytest

from modules import service


# --- _task_xml: содержимое задачи планировщика --------------------------------

def test_task_xml_has_boot_trigger_and_system_principal():
    xml = service._task_xml()
    assert "<BootTrigger>" in xml
    assert "<UserId>S-1-5-18</UserId>" in xml  # SYSTEM
    assert "<LogonType>ServiceAccount</LogonType>" in xml
    assert "<RunLevel>HighestAvailable</RunLevel>" in xml
    assert "service run" in xml


# --- install/uninstall: --dry-run не должен звать schtasks ---------------------

def test_install_dry_run_prints_xml_and_does_not_call_schtasks(monkeypatch, capsys):
    def _boom(*a, **kw):
        raise AssertionError("schtasks не должен звататься при --dry-run")
    monkeypatch.setattr(service.subprocess, "run", _boom)

    result = service.install(dry_run=True)

    assert result["dry_run"] is True
    assert "<Task" in result["xml"]
    out = capsys.readouterr().out
    assert "<Task" in out


def test_uninstall_dry_run_prints_command_and_does_not_call_schtasks(monkeypatch, capsys):
    def _boom(*a, **kw):
        raise AssertionError("schtasks не должен звататься при --dry-run")
    monkeypatch.setattr(service.subprocess, "run", _boom)

    result = service.uninstall(dry_run=True)

    assert result["dry_run"] is True
    assert "schtasks" in result["command"]
    assert "/Delete" in result["command"]
    out = capsys.readouterr().out
    assert "schtasks" in out


def test_install_real_calls_schtasks_create(monkeypatch, tmp_path):
    calls = []

    def _fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(service.subprocess, "run", _fake_run)

    result = service.install(dry_run=False)

    assert result == {"installed": True}
    assert len(calls) == 1
    assert calls[0][:3] == ["schtasks", "/Create", "/TN"]
    assert service.TASK_NAME in calls[0]


def test_install_raises_on_schtasks_failure(monkeypatch):
    monkeypatch.setattr(
        service.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr="кривой XML"),
    )
    with pytest.raises(RuntimeError, match="кривой XML"):
        service.install(dry_run=False)


# --- is_installed / status ------------------------------------------------------

def test_is_installed_true_on_returncode_zero(monkeypatch):
    monkeypatch.setattr(
        service.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert service.is_installed() is True


def test_is_installed_false_on_nonzero(monkeypatch):
    monkeypatch.setattr(
        service.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert service.is_installed() is False


def test_status_combines_installed_running_and_pid(monkeypatch):
    monkeypatch.setattr(service, "is_installed", lambda: True)
    monkeypatch.setattr(service, "is_running", lambda: True)
    monkeypatch.setattr(service, "_read_pid", lambda: 4242)

    st = service.status()

    assert st == {"installed": True, "running": True, "pid": 4242}


def test_status_no_pid_when_not_running(monkeypatch):
    monkeypatch.setattr(service, "is_installed", lambda: False)
    monkeypatch.setattr(service, "is_running", lambda: False)
    monkeypatch.setattr(service, "_read_pid", lambda: 4242)

    st = service.status()

    assert st == {"installed": False, "running": False, "pid": None}


# --- is_running / send_stop: обёртки над именованными объектами ---------------

def test_is_running_true_when_mutex_opens(monkeypatch):
    monkeypatch.setattr(service, "_open_mutex", lambda name: 123)
    closed = []
    monkeypatch.setattr(service, "_close_handle", lambda h: closed.append(h))

    assert service.is_running() is True
    assert closed == [123]


def test_is_running_false_when_mutex_missing(monkeypatch):
    monkeypatch.setattr(service, "_open_mutex", lambda name: None)
    assert service.is_running() is False


def test_send_stop_false_when_not_running(monkeypatch):
    monkeypatch.setattr(service, "is_running", lambda: False)
    assert service.send_stop() is False


def test_send_stop_sets_event_when_running(monkeypatch):
    monkeypatch.setattr(service, "is_running", lambda: True)
    monkeypatch.setattr(service, "_open_event", lambda name: 77)
    set_calls = []
    monkeypatch.setattr(service, "_set_event", lambda h: set_calls.append(h))
    closed = []
    monkeypatch.setattr(service, "_close_handle", lambda h: closed.append(h))

    assert service.send_stop() is True
    assert set_calls == [77]
    assert closed == [77]


def test_stop_task_reports_signaled_flag(monkeypatch):
    monkeypatch.setattr(service, "send_stop", lambda: True)
    assert service.stop_task() == {"signaled": True}


def test_start_task_requires_installed(monkeypatch):
    monkeypatch.setattr(service, "is_installed", lambda: False)
    with pytest.raises(RuntimeError, match="не установлена"):
        service.start_task()


# --- autostart_modules: общая логика UI/service --------------------------------

def test_autostart_modules_starts_everything_when_flagged_and_admin(monkeypatch):
    calls = []
    tg = SimpleNamespace(config={"autostart": True}, start=lambda: calls.append("tg"))
    winws = SimpleNamespace(config={"autostart": True}, autostart=lambda: calls.append("winws"))
    proxy = SimpleNamespace(config={"autostart": True, "mode": "tun"},
                            start=lambda: calls.append("proxy"))
    monkeypatch.setattr(service, "is_admin", lambda: True)

    service.autostart_modules(tg, winws, proxy)

    assert calls == ["tg", "winws", "proxy"]


def test_autostart_modules_skips_winws_without_admin(monkeypatch):
    calls = []
    tg = SimpleNamespace(config={"autostart": False}, start=lambda: None)
    winws = SimpleNamespace(config={"autostart": True}, autostart=lambda: calls.append("winws"))
    proxy = SimpleNamespace(config={"autostart": False, "mode": "pac"}, start=lambda: None)
    monkeypatch.setattr(service, "is_admin", lambda: False)
    logged = []

    service.autostart_modules(tg, winws, proxy, log=logged.append)

    assert calls == []
    assert any("администратора" in msg for msg in logged)


def test_autostart_modules_skips_pac_proxy_when_not_allowed(monkeypatch):
    calls = []
    tg = SimpleNamespace(config={"autostart": False}, start=lambda: None)
    winws = SimpleNamespace(config={"autostart": False}, autostart=lambda: None)
    proxy = SimpleNamespace(config={"autostart": True, "mode": "pac"},
                            start=lambda: calls.append("proxy"))
    logged = []

    service.autostart_modules(tg, winws, proxy, log=logged.append, allow_proxy_pac=False)

    assert calls == []
    assert any("PAC" in msg for msg in logged)


def test_autostart_modules_allows_tun_proxy_even_when_pac_forbidden(monkeypatch):
    calls = []
    tg = SimpleNamespace(config={"autostart": False}, start=lambda: None)
    winws = SimpleNamespace(config={"autostart": False}, autostart=lambda: None)
    proxy = SimpleNamespace(config={"autostart": True, "mode": "tun"},
                            start=lambda: calls.append("proxy"))

    service.autostart_modules(tg, winws, proxy, allow_proxy_pac=False)

    assert calls == ["proxy"]


def test_autostart_modules_allows_pac_proxy_for_ui_by_default(monkeypatch):
    calls = []
    tg = SimpleNamespace(config={"autostart": False}, start=lambda: None)
    winws = SimpleNamespace(config={"autostart": False}, autostart=lambda: None)
    proxy = SimpleNamespace(config={"autostart": True, "mode": "pac"},
                            start=lambda: calls.append("proxy"))

    service.autostart_modules(tg, winws, proxy)  # allow_proxy_pac=True по умолчанию

    assert calls == ["proxy"]


def test_autostart_modules_catches_exceptions_and_logs(monkeypatch):
    def boom():
        raise RuntimeError("порт занят")
    tg = SimpleNamespace(config={"autostart": True}, start=boom)
    winws = SimpleNamespace(config={"autostart": False}, autostart=lambda: None)
    proxy = SimpleNamespace(config={"autostart": False, "mode": "pac"}, start=lambda: None)
    logged = []

    service.autostart_modules(tg, winws, proxy, log=logged.append)

    assert any("порт занят" in msg for msg in logged)


# --- CLI --------------------------------------------------------------------

def test_cli_install_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(service, "is_supported", lambda: True)

    def _boom(*a, **kw):
        raise AssertionError("schtasks не должен звататься при --dry-run")
    monkeypatch.setattr(service.subprocess, "run", _boom)

    rc = service.cli(["install", "--dry-run"])

    assert rc == 0
    assert "<Task" in capsys.readouterr().out


def test_cli_status_prints_state(monkeypatch, capsys):
    monkeypatch.setattr(service, "is_supported", lambda: True)
    monkeypatch.setattr(service, "status", lambda: {"installed": True, "running": False, "pid": None})

    rc = service.cli(["status"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "да" in out  # installed
    assert "нет" in out  # running


def test_cli_unsupported_platform(monkeypatch, capsys):
    monkeypatch.setattr(service, "is_supported", lambda: False)

    rc = service.cli(["status"])

    assert rc == 1
    assert "Windows" in capsys.readouterr().out


# --- наблюдатель за lists/*.txt в службе -------------------------------------------

def test_start_lists_watch_applies_file_events_to_service_modules(monkeypatch):
    import threading

    from modules import filewatch

    started = {}

    class FakeWatcher:
        def __init__(self, on_change, **kw):
            started["on_change"], started["kw"] = on_change, kw

        def start_background(self, stop):
            started["stop"] = stop

    monkeypatch.setattr(filewatch, "ListsWatcher", FakeWatcher)
    calls = []
    winws = SimpleNamespace(config={"lists": ["discord"]}, refresh_user_lists=lambda: calls.append("winws"))
    proxy = SimpleNamespace(config={"lists": []}, reload_lists=lambda: calls.append("proxy"))
    hosts = SimpleNamespace(assignments=lambda: {}, resync=lambda: calls.append("hosts"))
    stop = threading.Event()
    logged = []

    service.start_lists_watch(winws, proxy, hosts, stop, logged.append)

    assert started["stop"] is stop and started["kw"]["log"] == logged.append
    assert started["on_change"]("changed", "discord") == []
    assert calls == ["winws"]
