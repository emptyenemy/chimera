"""modules/control.py — локальный канал управления, через который CLI говорит с работающей Chimera.

Сервер поднимаем на 127.0.0.1 с фиктивным Api: настоящий Api запускал бы winws2 и hosts.
Файл со связью (порт и токен) уводим во временную папку.
"""

import http.client
import json
import os
import threading

import pytest

from modules import control


class FakeApi:
    def __init__(self):
        self.calls = []
        self.shutdowns = 0
        self.quits = threading.Event()

    def dispatch(self, method, args_json):
        self.calls.append((method, json.loads(args_json)))
        return json.dumps({"ok": True, "data": {"running": True, "link": "vless://uuid@1.2.3.4:443?x=1",
                                                  "secret": "abcdef", "name": "n"}})

    def shutdown(self):
        self.shutdowns += 1

    def request_quit(self):
        self.quits.set()


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "CONTROL_PATH", tmp_path / "control.json")
    api = FakeApi()
    srv = control.ControlServer(api)
    srv.start()
    yield srv, api
    srv.stop()


def _request(srv, method, path, body=None, headers=None, token=True, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    hdrs = dict(headers or {})
    if token is True:
        hdrs[control.TOKEN_HEADER] = srv.token
    elif token:
        hdrs[control.TOKEN_HEADER] = token
    if host:
        hdrs["Host"] = host
    data = json.dumps(body).encode() if body is not None else None
    if data:
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except ValueError:
        return resp.status, raw


def test_hello_reports_protocol_and_version(server):
    srv, _ = server
    status, body = _request(srv, "GET", "/hello")
    assert status == 200
    assert body["protocol"] == control.PROTOCOL
    assert body["pid"] == os.getpid()
    assert "version" in body


def test_requests_without_or_with_wrong_token_are_refused(server):
    srv, api = server
    assert _request(srv, "GET", "/hello", token=False)[0] == 403
    assert _request(srv, "GET", "/hello", token="nope")[0] == 403
    assert _request(srv, "POST", "/api", {"method": "app_info", "args": []}, token=False)[0] == 403
    assert api.calls == []


def test_foreign_host_header_is_refused(server):
    # защита от подмены DNS: чужая страница в браузере не должна достучаться до канала
    srv, api = server
    status, _ = _request(srv, "POST", "/api", {"method": "app_info", "args": []}, host="evil.example")
    assert status == 403
    assert api.calls == []


def test_browser_origin_is_refused(server):
    srv, api = server
    status, _ = _request(srv, "POST", "/api", {"method": "app_info", "args": []},
                         headers={"Origin": "http://evil.example"})
    assert status == 403
    assert api.calls == []


def test_allowed_method_is_dispatched_with_list_args(server):
    srv, api = server
    status, body = _request(srv, "POST", "/api", {"method": "winws_start", "args": ["general"]})
    assert status == 200 and body["ok"] is True
    assert api.calls == [("winws_start", ["general"])]


def test_args_may_come_as_json_string(server):
    srv, api = server
    _request(srv, "POST", "/api", {"method": "winws_start", "args": json.dumps(["alt"])})
    assert api.calls == [("winws_start", ["alt"])]


def test_method_outside_allowlist_is_forbidden_and_not_called(server):
    srv, api = server
    # подписки окна и открытие ссылок в браузере CLI не нужны — набор методов задан таблицей команд
    status, body = _request(srv, "POST", "/api", {"method": "hub_watch", "args": [[], True]})
    assert body["ok"] is False and body["code"] == "forbidden"
    _, body2 = _request(srv, "POST", "/api", {"method": "open_url", "args": ["http://x"]})
    assert body2["code"] == "forbidden"
    assert api.calls == []
    assert "open_url" not in control.ALLOWED_METHODS and "hub_watch" not in control.ALLOWED_METHODS


def test_private_method_name_is_forbidden(server):
    srv, api = server
    _, body = _request(srv, "POST", "/api", {"method": "_autostart_all", "args": []})
    assert body["code"] == "forbidden" and api.calls == []


def test_secrets_are_masked_unless_revealed(server):
    srv, _ = server
    _, masked = _request(srv, "POST", "/api", {"method": "proxy_state", "args": []})
    assert "1.2.3.4" not in json.dumps(masked) and "abcdef" not in json.dumps(masked)
    assert masked["data"]["link"].startswith("vless://")  # схема видна, содержимое скрыто
    assert masked["data"]["running"] is True

    _, raw = _request(srv, "POST", "/api", {"method": "proxy_state", "args": [], "reveal": True})
    assert raw["data"]["link"] == "vless://uuid@1.2.3.4:443?x=1"
    assert raw["data"]["secret"] == "abcdef"


def test_config_set_only_for_safe_keys(server):
    srv, api = server
    _, bad = _request(srv, "POST", "/api", {"method": "config_set", "args": ["interface", "service"]})
    assert bad["code"] == "forbidden"
    _, bad2 = _request(srv, "POST", "/api", {"method": "config_set", "args": ["game_filter", "all"]})
    assert bad2["code"] == "forbidden"
    assert api.calls == []
    _, ok = _request(srv, "POST", "/api", {"method": "config_set", "args": ["update_channel", "beta"]})
    assert ok["ok"] is True
    assert api.calls == [("config_set", ["update_channel", "beta"])]


def test_bad_request_body_is_400(server):
    srv, _ = server
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("POST", "/api", body=b"not json", headers={control.TOKEN_HEADER: srv.token})
    assert conn.getresponse().status == 400
    conn.close()


def test_discovery_file_is_written_and_removed(tmp_path, monkeypatch):
    path = tmp_path / "control.json"
    monkeypatch.setattr(control, "CONTROL_PATH", path)
    srv = control.ControlServer(FakeApi())
    srv.start()
    info = control.read_discovery()
    assert info["port"] == srv.port and info["token"] == srv.token
    assert info["pid"] == os.getpid() and info["protocol"] == control.PROTOCOL
    srv.stop()
    assert control.read_discovery() is None and not path.exists()


def test_stop_does_not_remove_someone_elses_discovery_file(tmp_path, monkeypatch):
    path = tmp_path / "control.json"
    monkeypatch.setattr(control, "CONTROL_PATH", path)
    srv = control.ControlServer(FakeApi())
    srv.start()
    # запись успел перезаписать другой экземпляр — чужой файл не трогаем
    path.write_text(json.dumps({"port": 1, "token": "x", "pid": os.getpid() + 1, "protocol": 1}), encoding="utf-8")
    srv.stop()
    assert path.exists()


def test_read_discovery_ignores_broken_file(tmp_path, monkeypatch):
    path = tmp_path / "control.json"
    monkeypatch.setattr(control, "CONTROL_PATH", path)
    path.write_text("{oops", encoding="utf-8")
    assert control.read_discovery() is None


def test_quit_action_shuts_down_and_asks_backend_to_quit(server):
    srv, api = server
    status, body = _request(srv, "POST", "/control", {"action": "quit"})
    assert status == 200 and body["ok"] is True
    assert api.quits.wait(3)
    assert api.shutdowns == 1


def test_restart_action_spawns_relauncher_before_quit(server, monkeypatch):
    srv, api = server
    spawned = []
    monkeypatch.setattr(control, "spawn_relaunch", lambda: spawned.append(True))
    _, body = _request(srv, "POST", "/control", {"action": "restart"})
    assert body["ok"] is True
    assert api.quits.wait(3)
    assert spawned == [True]


def test_unknown_control_action_is_bad_request(server):
    srv, api = server
    _, body = _request(srv, "POST", "/control", {"action": "format_disk"})
    assert body["ok"] is False and body["code"] == "bad_request"
    assert not api.quits.is_set()


def test_relaunch_command_from_source_uses_main_py(monkeypatch):
    monkeypatch.setattr(control.paths, "IS_FROZEN", False)
    cmd = control.relaunch_command()
    assert cmd[-1] == "--window" and cmd[-2].endswith("main.py")


def test_relaunch_command_frozen_uses_the_exe(monkeypatch):
    monkeypatch.setattr(control.paths, "IS_FROZEN", True)
    cmd = control.relaunch_command()
    assert cmd == [control.sys.executable, "--window"]
