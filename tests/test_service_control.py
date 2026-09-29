"""Канал службы с подменёнными модулями и объектами Windows."""
import json
import urllib.request
from types import SimpleNamespace

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
