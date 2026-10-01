import json
from unittest.mock import Mock

import pytest

from tools import smoke_build


@pytest.mark.parametrize("url", [
    "file:///C:/Chimera/ui/web-next/index.html",
    "http://127.0.0.1:59917/",
    "http://127.0.0.1:59917/index.html",
])
def test_wait_cdp_accepts_app_page(monkeypatch, url):
    response = Mock()
    response.read.return_value = json.dumps([{"type": "page", "url": url + "?native=1#settings"}]).encode()
    monkeypatch.setattr(smoke_build.urllib.request, "urlopen", Mock(return_value=response))
    smoke_build._wait_cdp(9222, Mock(poll=Mock(return_value=None)), timeout=1)


@pytest.mark.parametrize("url", ["about:blank", "http://example.org/", "http://127.0.0.1:99/other"])
def test_wait_cdp_rejects_unrelated_page(monkeypatch, url):
    response = Mock()
    response.read.return_value = json.dumps([{"type": "page", "url": url}]).encode()
    monkeypatch.setattr(smoke_build.urllib.request, "urlopen", Mock(return_value=response))
    monkeypatch.setattr(smoke_build.time, "sleep", lambda _: None)
    ticks = iter([0, 0.01, 1])
    monkeypatch.setattr(smoke_build.time, "time", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="CDP"):
        smoke_build._wait_cdp(9222, Mock(poll=Mock(return_value=None)), timeout=0.1)


def test_status_validates_the_compiled_flavor():
    import json

    text = json.dumps({"ok": True, "data": {"app": {"flavor": "lite"}}})
    assert smoke_build._json_flavor(text, "lite")
    assert not smoke_build._json_flavor(text, "qt")
    assert not smoke_build._json_flavor('{"ok":true}', "qt")
    assert not smoke_build._json_flavor('not json', "qt")
