import http.cookiejar
import urllib.error
import urllib.request
from unittest.mock import Mock

import pytest

from ui import backend_webview


def test_native_page_and_resources_use_authenticated_session(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text('<html><head><link href="/app.css" rel="stylesheet"></head><body></body></html>')
    (tmp_path / "app.css").write_text("body { color: red; }")
    monkeypatch.setattr(backend_webview, "web_dir", lambda: tmp_path)
    monkeypatch.setattr(backend_webview.theme, "boot_script", lambda _: "window.boot=true;")
    server, url = backend_webview._asset_server(Mock())
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url.split("?", 1)[0])
        assert error.value.code == 403
        jar = http.cookiejar.CookieJar()
        browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        with browser.open(url) as response:
            page = response.read().decode()
        assert "window.boot=true" in page
        assert "__CHIMERA_HTTP__" not in page
        assert "__CHIMERA_TOKEN__" not in page
        assert any(cookie.name == "chimera_token" for cookie in jar)
        with browser.open(url.split("?", 1)[0] + "app.css") as response:
            assert response.status == 200
            assert "color: red" in response.read().decode()
    finally:
        server.shutdown()
        server.server_close()
