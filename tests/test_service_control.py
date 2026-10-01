"""Канал службы с подменёнными модулями и объектами Windows."""
import json
import urllib.request
from types import SimpleNamespace

import pytest

from modules import control, service
from ui import api as api_mod


def test_service_exposes_api_and_closes_discovery(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(control, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(control, "_restrict_permissions", lambda path: None)
    monkeypatch.setattr(control, "_current_sid", lambda: "test-user")
    monkeypatch.setattr(service, "LOG_PATH", tmp_path / "service.log")
    monkeypatch.setattr(service, "is_supported", lambda: True)
    monkeypatch.setattr(service, "_create_mutex", lambda name: 1)
    monkeypatch.setattr(service.ctypes, "get_last_error", lambda: 0)
    monkeypatch.setattr(service, "_create_event", lambda name: 2)
    monkeypatch.setattr(service, "_write_pid", lambda: None)
    monkeypatch.setattr(service, "_remove_pid", lambda: calls.append("pid-removed"))
    monkeypatch.setattr(service, "_close_handle", lambda handle: calls.append(handle))

    class FakeApi:
        def __init__(self, *, service_owned):
            assert service_owned
            self.tg = self.winws = self.proxy = SimpleNamespace(config={"autostart": False})
            self._trial = SimpleNamespace(active=None)

        def dispatch(self, method, args):
            return json.dumps({"ok": True, "data": {"service_running": True}})

        def shutdown(self):
            control.stop_current()
            calls.append("shutdown")

    monkeypatch.setattr(api_mod, "Api", FakeApi)

    def wait(handle, timeout):
        info = control.read_discovery()
        request = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api",
            data=json.dumps({"method": "app_info", "args": "[]"}).encode(),
            headers={"X-Chimera-Token": info["token"], "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            assert json.load(response)["data"]["service_running"]
        return 0

    monkeypatch.setattr(service, "_wait_event", wait)
    try:
        assert service.run() == 0
        assert control.read_discovery() is None
        assert calls == ["shutdown", "pid-removed", 2, 1]
    finally:
        control.stop_current()


def test_owned_api_stops_modules_even_while_service_mutex_exists(monkeypatch):
    calls = []
    api = api_mod.Api.__new__(api_mod.Api)
    api._service_owned = True
    api._bg_stop = SimpleNamespace(set=lambda: calls.append("background"))
    api.hub = SimpleNamespace(stop=lambda: calls.append("hub"))
    api.hosts = SimpleNamespace(stop_background=lambda: calls.append("hosts"))
    for name in ("winws", "proxy", "tg"):
        setattr(api, name, SimpleNamespace(stop=lambda n=name: calls.append(n)))
    monkeypatch.setattr(control, "stop_current", lambda: None)
    monkeypatch.setattr(service, "is_running", lambda: True)
    api.shutdown()
    api.shutdown()
    assert calls == ["hub", "background", "hosts", "winws", "proxy", "tg"]


def test_service_releases_handles_when_api_start_fails(monkeypatch, tmp_path):
    closed = []
    monkeypatch.setattr(service, "LOG_PATH", tmp_path / "service.log")
    monkeypatch.setattr(service, "is_supported", lambda: True)
    monkeypatch.setattr(service, "_create_mutex", lambda name: 1)
    monkeypatch.setattr(service.ctypes, "get_last_error", lambda: 0)
    monkeypatch.setattr(service, "_create_event", lambda name: 2)
    monkeypatch.setattr(service, "_write_pid", lambda: None)
    monkeypatch.setattr(service, "_remove_pid", lambda: closed.append("pid"))
    monkeypatch.setattr(service, "_close_handle", closed.append)

    def fail(**kwargs):
        raise RuntimeError("startup failed")

    monkeypatch.setattr(api_mod, "Api", fail)
    with pytest.raises(RuntimeError, match="startup failed"):
        service.run()
    assert closed == ["pid", 2, 1]


def test_service_rotates_token_when_console_user_changes(monkeypatch):
    server = SimpleNamespace(port=1234, token="old-token")
    written = []
    monkeypatch.setattr(control, "_server", server)
    monkeypatch.setattr(control, "_service_access_sid", "old-user")
    monkeypatch.setattr(control, "_service_access_check", 0)
    monkeypatch.setattr(control, "_current_sid", lambda: "S-1-5-18")
    monkeypatch.setattr(control, "_interactive_sid", lambda: "new-user")
    monkeypatch.setattr(control, "write_discovery", lambda port, token, **kw: written.append((port, token, kw)))
    control.refresh_service_access()
    assert server.token != "old-token"
    assert written == [(1234, server.token, {"interactive_sid": "new-user"})]


def test_discovery_recreation_grants_the_same_user_on_the_new_file(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(control, "_service_access_sid", "user-sid")
    monkeypatch.setattr(control, "_interactive_sid", lambda: "user-sid")
    monkeypatch.setattr(control.subprocess, "run", lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0))
    control._grant_service_user(tmp_path / "control.tmp", force=True)
    assert calls[-1][-1] == "*user-sid:R"
