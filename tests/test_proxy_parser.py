"""modules/proxy/parser.py — разбор share-ссылок vless/trojan/ss/vmess.

Только чистый разбор строки в outbound-словарь, без сети и без запуска sing-box.
"""

import base64
import json

import pytest

from modules.proxy import parser


# --- vless -------------------------------------------------------------------


def test_vless_minimal_no_tls():
    r = parser.parse_link("vless://uuid-1@example.com:443?security=none#Label")
    assert r["protocol"] == "vless"
    assert r["server"] == "example.com:443"
    assert r["label"] == "Label"
    assert r["security"] == "none"
    ob = r["outbound"]
    assert ob == {"type": "vless", "server": "example.com", "server_port": 443,
                  "uuid": "uuid-1"}


def test_vless_reality_with_fp():
    link = ("vless://uuid@host.example:443?security=reality&sni=s.example"
            "&fp=chrome&pbk=PBK&sid=SID&type=tcp#reality-test")
    r = parser.parse_link(link)
    assert r["security"] == "reality"
    tls = r["outbound"]["tls"]
    assert tls["server_name"] == "s.example"
    assert tls["reality"] == {"enabled": True, "public_key": "PBK", "short_id": "SID"}
    assert tls["utls"] == {"enabled": True, "fingerprint": "chrome"}
    assert "transport" not in r["outbound"]  # type=tcp -> без transport


def test_vless_reality_without_fp_defaults_utls_chrome():
    """Без явного fp reality всё равно включает utls с фингерпринтом по умолчанию."""
    link = "vless://uuid@host.example:443?security=reality&sni=s.example&pbk=PBK&sid=SID#x"
    r = parser.parse_link(link)
    assert r["outbound"]["tls"]["utls"] == {"enabled": True, "fingerprint": "chrome"}


def test_vless_ws_transport_with_host_header():
    link = "vless://uuid@host.example:443?security=none&type=ws&path=%2Fmy%2Fpath&host=cdn.example#ws"
    r = parser.parse_link(link)
    assert r["outbound"]["transport"] == {
        "type": "ws", "path": "/my/path", "headers": {"Host": "cdn.example"}
    }


def test_vless_grpc_transport_service_name():
    link = "vless://uuid@host.example:443?security=none&type=grpc&serviceName=mysvc#grpc"
    r = parser.parse_link(link)
    assert r["outbound"]["transport"] == {"type": "grpc", "service_name": "mysvc"}


def test_vless_http_transport_multi_host():
    link = "vless://uuid@host.example:80?security=none&type=http&host=a.com,b.com&path=%2Fhp#http"
    r = parser.parse_link(link)
    assert r["outbound"]["transport"] == {"type": "http", "host": ["a.com", "b.com"], "path": "/hp"}


def test_vless_ipv6_host():
    """IPv6-хост в квадратных скобках — urlsplit сам снимает скобки."""
    link = "vless://uuid@[2001:db8::1]:8443?security=none#ipv6"
    r = parser.parse_link(link)
    assert r["outbound"]["server"] == "2001:db8::1"
    assert r["outbound"]["server_port"] == 8443


def test_vless_ipv6_server_display_bracketed():
    link = "vless://uuid@[2001:db8::1]:8443?security=none#ipv6"
    r = parser.parse_link(link)
    assert r["server"] == "[2001:db8::1]:8443"


def test_vless_percent_encoded_label():
    link = "vless://uuid@example.com:443?security=none#My%20Server%20%231"
    r = parser.parse_link(link)
    assert r["label"] == "My Server #1"


def test_vless_label_fallback_to_server_when_no_fragment():
    link = "vless://uuid@example.com:443?security=none"
    r = parser.parse_link(link)
    assert r["label"] == "example.com:443"


def test_vless_missing_port_raises():
    with pytest.raises(ValueError, match="host:port"):
        parser.parse_link("vless://uuid@example.com")


def test_vless_flow_passed_through():
    link = "vless://uuid@example.com:443?security=none&flow=xtls-rprx-vision#flow"
    r = parser.parse_link(link)
    assert r["outbound"]["flow"] == "xtls-rprx-vision"


# --- trojan --------------------------------------------------------------------


def test_trojan_tls_enabled_by_default_without_security_param():
    """У trojan TLS включён даже без явного security= в ссылке."""
    link = "trojan://secretpass@host.example:443#trojan"
    r = parser.parse_link(link)
    assert r["security"] == "tls"
    assert r["outbound"]["tls"]["enabled"] is True
    assert r["outbound"]["tls"]["server_name"] == "host.example"


def test_trojan_percent_encoded_password():
    link = "trojan://p%40ss%3Aword@host.example:443#pw"
    r = parser.parse_link(link)
    assert r["outbound"]["password"] == "p@ss:word"


def test_trojan_missing_host_raises():
    with pytest.raises(ValueError, match="host:port"):
        parser.parse_link("trojan://pass@:443")


# --- shadowsocks -----------------------------------------------------------------


def test_ss_sip002_format():
    userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:mypassword").decode().rstrip("=")
    link = f"ss://{userinfo}@example.com:8388#SS%20Label"
    r = parser.parse_link(link)
    assert r["label"] == "SS Label"
    assert r["outbound"] == {"type": "shadowsocks", "server": "example.com",
                              "server_port": 8388, "method": "aes-256-gcm",
                              "password": "mypassword"}


def test_ss_legacy_fully_encoded_format():
    body = base64.urlsafe_b64encode(b"aes-256-gcm:mypassword@example.com:8388").decode().rstrip("=")
    link = f"ss://{body}#legacy"
    r = parser.parse_link(link)
    assert r["outbound"]["server"] == "example.com"
    assert r["outbound"]["server_port"] == 8388
    assert r["outbound"]["method"] == "aes-256-gcm"


def test_ss_malformed_base64_raises_value_error():
    """binascii.Error — подкласс ValueError, так что снаружи ловится как обычная
    невалидная ссылка (хотя сообщение об ошибке будет неинформативным)."""
    with pytest.raises(ValueError):
        parser.parse_link("ss://!!!not-base64!!!")


# --- vmess -----------------------------------------------------------------------


def _vmess_link(cfg: dict) -> str:
    body = base64.b64encode(json.dumps(cfg).encode()).decode()
    return f"vmess://{body}"


def test_vmess_basic_ws_tls():
    cfg = {"add": "example.com", "port": "443", "id": "uuid-vmess", "aid": "0",
           "net": "ws", "path": "/ws", "host": "example.com", "tls": "tls",
           "sni": "example.com"}
    r = parser.parse_link(_vmess_link(cfg))
    assert r["protocol"] == "vmess"
    assert r["security"] == "tls"
    ob = r["outbound"]
    assert ob["server"] == "example.com"
    assert ob["server_port"] == 443
    assert ob["uuid"] == "uuid-vmess"
    assert ob["alter_id"] == 0
    assert ob["transport"] == {"type": "ws", "path": "/ws", "headers": {"Host": "example.com"}}
    assert ob["tls"]["server_name"] == "example.com"


def test_vmess_missing_add_or_port_raises():
    with pytest.raises(ValueError, match="add/port"):
        parser.parse_link(_vmess_link({"id": "uuid"}))


def test_vmess_label_from_ps_field():
    cfg = {"add": "example.com", "port": 443, "id": "uuid", "ps": "MyVmessName"}
    r = parser.parse_link(_vmess_link(cfg))
    assert r["label"] == "MyVmessName"


# --- общие ошибки -----------------------------------------------------------------


def test_no_scheme_raises():
    with pytest.raises(ValueError, match="scheme"):
        parser.parse_link("not-a-link-at-all")


def test_unsupported_scheme_raises():
    with pytest.raises(ValueError, match="ssh"):
        parser.parse_link("ssh://foo@bar:22")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        parser.parse_link("")
