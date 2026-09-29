"""Переключатель фронта (config.json -> frontend): legacy по умолчанию, next — если собран."""

import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from modules import appconfig
from ui import backend_browser, frontend


@pytest.fixture
def cfg(monkeypatch):
    """Подменяет конфиг: cfg(frontend="next") или cfg() — ключа нет вовсе."""
    def setup(**values):
        monkeypatch.setattr(appconfig, "load", lambda: dict(values))
    return setup


@pytest.fixture
def built(monkeypatch, tmp_path):
    """Каталог «собранного» нового фронта."""
    (tmp_path / "index.html").write_text("<html><head></head><body>next</body></html>", encoding="utf-8")
    monkeypatch.setattr(frontend, "NEXT_DIR", tmp_path)
    return tmp_path


def test_next_is_default(cfg, built):
    cfg()
    assert frontend.selected() == "next"
    assert frontend.web_dir() == built
    assert not frontend.next_missing()


def test_old_or_unknown_value_uses_next(cfg):
    cfg(frontend="что-то")
    assert frontend.selected() == "next"


def test_next_uses_build(cfg, built):
    cfg(frontend="next")
    assert frontend.web_dir() == built
    assert not frontend.next_missing()


def test_next_without_build_falls_back_and_says_why(cfg, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(frontend, "NEXT_DIR", tmp_path / "нет-такой")
    cfg(frontend="next")
    assert frontend.next_missing()
    with pytest.raises(FileNotFoundError, match="npm run build"):
        frontend.web_dir()


def test_window_icon_does_not_depend_on_web_dir():
    from ui import backend_qt
    assert backend_qt.APP_ICON.exists()


def _get(server, path="/"):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    req = urllib.request.Request(url, headers={"X-Chimera-Token": "t"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


@pytest.fixture
def server():
    made = []

    def start(web_dir, missing_next=False):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), backend_browser._Handler)
        srv.daemon_threads = True
        srv.api, srv.hub, srv.token = None, backend_browser._Hub(), "t"
        srv.web_dir, srv.missing_next = web_dir, missing_next
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return srv

    yield start
    for srv in made:
        srv.shutdown()
        srv.server_close()


def test_browser_serves_next_build(server, built):
    (built / "app.js").write_text("1", encoding="utf-8")
    srv = server(built)
    status, body = _get(srv)
    assert status == 200 and "next" in body and "__CHIMERA_HTTP__" in body  # маркер движка на месте
    assert _get(srv, "/app.js")[0] == 200
    assert _get(srv, "/../secret")[0] == 404


def test_browser_shows_hint_when_next_is_not_built(server, tmp_path):
    srv = server(tmp_path / "нет-такой", missing_next=True)
    status, body = _get(srv)
    assert status == 200 and "npm run build" in body
    assert _get(srv, "/index.html")[0] == 404


def test_browser_default_dir_is_next(server):
    srv = server(None)
    status, body = _get(srv)
    assert status == 200 and "<title>Chimera</title>" in body
