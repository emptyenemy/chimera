"""Подписка прокси: разбор форматов провайдеров, выбор самого быстрого сервера и секреты."""

import base64
import io
import json

import pytest

from modules import control
from modules.errors import ChimeraError
from modules.proxy import manager as proxy_manager
from modules.proxy import subscription
from modules.proxy.manager import ProxyManager

VLESS_A = "vless://11111111-1111-1111-1111-111111111111@a.example:443?security=tls&sni=a.example#A"
VLESS_B = "vless://22222222-2222-2222-2222-222222222222@b.example:443?security=tls&sni=b.example#B"
TROJAN = "trojan://secret@c.example:443?sni=c.example#C"
HY2 = "hysteria2://pass@d.example:8443?sni=d.example#D"


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@pytest.mark.parametrize("raw, ok", [
    ("https://sub.example/api/v1/client/subscribe?token=abc", True), ("https://sub.example/s/abc", True),
    ("https://sub.example/", False), ("https://t.me/socks?server=1.2.3.4&port=1080", False),
    (VLESS_A, False), ("not a url", False), ("https://a.example/x\nhttps://b.example/y", False),
])
def test_subscription_addresses_are_told_from_server_links(raw, ok):
    assert subscription.is_subscription_url(raw) is ok


def test_base64_list_from_v2rayn_style_providers():
    text = b64("\n".join([VLESS_A, "garbage line", TROJAN, VLESS_A, "vless://broken", HY2]))
    assert subscription.links(text) == [VLESS_A, TROJAN, HY2]


def test_plain_links_and_singbox_json_outbounds():
    assert subscription.links(f"{VLESS_A}\r\n{VLESS_B}\n") == [VLESS_A, VLESS_B]
    config = {"outbounds": [{"type": "direct", "tag": "direct"},
                            {"type": "trojan", "tag": "nl", "server": "e.example", "server_port": 443, "password": "p",
                             "tls": {"enabled": True, "server_name": "e.example"}}]}
    found = subscription.links(json.dumps(config))
    assert len(found) == 1 and json.loads(found[0])["server"] == "e.example"


def test_fastest_tcp_server_wins_and_quic_is_only_a_fallback():
    servers = [VLESS_A, VLESS_B, HY2]
    assert subscription.choose(servers, [120, 40, None]) == 1
    assert subscription.choose(servers, [None, None, None]) == 2
    assert subscription.choose([VLESS_A], [None]) == 0


def test_ping_measures_tcp_and_skips_quic():
    ticks = iter([1.0, 1.085])

    class Conn:
        def close(self):
            pass

    assert subscription.ping(VLESS_A, connect=lambda addr, timeout: Conn(), now=lambda: next(ticks)) == 85
    assert subscription.ping(HY2, connect=lambda addr, timeout: pytest.fail("no tcp for quic")) is None
    assert subscription.ping(VLESS_A, connect=lambda addr, timeout: (_ for _ in ()).throw(OSError("refused"))) is None


def test_download_errors_are_coded():
    with pytest.raises(ChimeraError) as e:
        subscription.fetch("https://sub.example/x", opener=lambda req, timeout: (_ for _ in ()).throw(OSError("timeout")))
    assert e.value.code == "err.proxy.subscription.fetch"
    with pytest.raises(ChimeraError) as e:
        subscription.fetch("https://sub.example/x", opener=lambda req, timeout: io.BytesIO(b"x" * (subscription.MAX_BYTES + 1)))
    assert e.value.code == "err.proxy.subscription.too_big"


@pytest.fixture
def pm(monkeypatch, tmp_path):
    monkeypatch.setattr(proxy_manager, "STATE_PATH", tmp_path / "proxy.json")
    monkeypatch.setattr(ProxyManager, "running", property(lambda self: False))
    monkeypatch.setattr(ProxyManager, "_system_pids", staticmethod(lambda: []))
    pings = {VLESS_A: 120, VLESS_B: 40, TROJAN: None, HY2: None}
    monkeypatch.setattr(subscription, "ping_all", lambda servers, ping_fn=None: [pings.get(s) for s in servers])
    monkeypatch.setattr(subscription, "fetch", lambda url, opener=None: b64(f"{VLESS_A}\n{VLESS_B}\n{TROJAN}"))
    return ProxyManager()


def test_subscription_address_downloads_servers_and_picks_the_fastest(pm):
    state = pm.set_link("https://sub.example/s/token123")
    assert pm.config["link"] == VLESS_B and pm.config["servers"] == [VLESS_A, VLESS_B, TROJAN]
    assert state["subscription"] == "https://sub.example/s/token123"
    assert [(r["index"], r["label"], r["ms"], r["current"]) for r in state["servers"]] == [
        (0, "A", 120, False), (1, "B", 40, True), (2, "C", None, False)]
    assert all("link" not in r and "uuid" not in json.dumps(r) for r in state["servers"])


def test_subscription_address_is_hidden_from_the_command_line(pm):
    state = pm.set_link("https://sub.example/s/token123")
    shown = control.redact(state)
    assert "token123" not in json.dumps(shown, ensure_ascii=False) and "1111" not in json.dumps(shown)


def test_a_manual_link_replaces_the_subscription(pm):
    pm.set_link("https://sub.example/s/token123")
    state = pm.set_link(TROJAN)
    assert state["subscription"] == "" and state["servers"] == [] and pm.config["link"] == TROJAN


def test_pasted_subscription_content_offers_its_servers_without_refresh(pm):
    state = pm.set_link(b64(f"{VLESS_A}\n{VLESS_B}"))
    assert pm.config["link"] == VLESS_B and state["subscription"] == "" and len(state["servers"]) == 2
    with pytest.raises(ChimeraError) as e:
        pm.refresh_subscription()
    assert e.value.code == "err.proxy.subscription.none"


def test_choosing_a_server_by_number_and_the_fastest(pm):
    pm.set_link("https://sub.example/s/token123")
    pm.select_server(0)
    assert pm.config["link"] == VLESS_A
    with pytest.raises(ChimeraError):
        pm.select_server(7)
    with pytest.raises(ChimeraError):
        pm.select_server(True)
    pm.select_fastest()
    assert pm.config["link"] == VLESS_B


def test_empty_subscription_changes_nothing(pm, monkeypatch):
    pm.set_link(TROJAN)
    monkeypatch.setattr(subscription, "fetch", lambda url, opener=None: "nothing here")
    with pytest.raises(ChimeraError) as e:
        pm.set_link("https://sub.example/s/other")
    assert e.value.code == "err.proxy.subscription.empty" and pm.config["link"] == TROJAN


def test_backups_accept_a_subscription_and_reject_garbage():
    from modules import configbackups
    ok = configbackups.normalize("proxy", {"link": VLESS_A, "subscription": "https://sub.example/s/x", "servers": [VLESS_A]})
    assert ok["servers"] == [VLESS_A]
    with pytest.raises(ChimeraError) as e:
        configbackups.normalize("proxy", {"link": VLESS_A, "servers": "not a list"})
    assert e.value.code == "err.backup.invalid"
