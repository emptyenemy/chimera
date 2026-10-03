"""modules/proxy/parser.py — разбор share-ссылок vless/trojan/ss/vmess, hysteria2, hysteria, tuic,
anytls, socks и http.

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
    with pytest.raises(ValueError, match="mieru"):
        parser.parse_link("mieru://foo@bar:22")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        parser.parse_link("")


def test_legacy_ss_ipv6_and_password_delimiters():
    body = base64.urlsafe_b64encode(b"aes-256-gcm:pass@word:extra@[2001:db8::1]:8388").decode().rstrip("=")
    result = parser.parse_link(f"ss://{body}#IPv6")
    assert result["server"] == "[2001:db8::1]:8388"
    assert result["outbound"]["password"] == "pass@word:extra"


@pytest.mark.parametrize("transport", ["ws", "http", "h2", "httpupgrade"])
def test_transport_path_decoded_once(transport):
    result = parser.parse_link(f"vless://uuid@example.com:443?type={transport}&path=%2Fliteral%252Fsegment")
    assert result["outbound"]["transport"]["path"] == "/literal%2Fsegment"


def test_vmess_transport_path_is_literal_json_string():
    result = parser.parse_link(_vmess_link({"add": "example.com", "port": 443, "id": "uuid",
                                           "net": "ws", "path": "/literal%2Fsegment"}))
    assert result["outbound"]["transport"]["path"] == "/literal%2Fsegment"


@pytest.mark.parametrize("port", [-1, 65536, 443.5, True, [], {}, "443.5", "not-a-port"])
def test_vmess_rejects_invalid_port_with_value_error(port):
    with pytest.raises(ValueError):
        parser.parse_link(_vmess_link({"add": "example.com", "port": port, "id": "uuid"}))


@pytest.mark.parametrize("payload", [None, [], 42, "not an object"])
def test_vmess_non_object_payload_is_value_error(payload):
    with pytest.raises(ValueError):
        parser.parse_link(_vmess_link(payload))


def test_ss_rejects_base64_with_inserted_junk():
    body = base64.urlsafe_b64encode(b"aes-256-gcm:password").decode().rstrip("=")
    with pytest.raises(ValueError):
        parser.parse_link(f"ss://{body[:4]}!{body[4:]}@example.com:8388")


@pytest.mark.parametrize("port", [-1, 65536])
def test_legacy_ss_rejects_invalid_port(port):
    body = base64.urlsafe_b64encode(f"aes-256-gcm:password@example.com:{port}".encode()).decode().rstrip("=")
    with pytest.raises(ValueError):
        parser.parse_link(f"ss://{body}")


@pytest.mark.parametrize("port", [1, 65535, "1", "65535"])
def test_vmess_accepts_port_boundaries(port):
    result = parser.parse_link(_vmess_link({"add": "example.com", "port": port, "id": "uuid"}))
    assert result["outbound"]["server_port"] == int(port)


@pytest.mark.parametrize("key,value", [("net", []), ("path", {}), ("add", []), ("id", 123),
                                      ("aid", -1), ("aid", 1.5), ("aid", True), ("aid", [])])
def test_vmess_invalid_fields_are_value_errors(key, value):
    cfg = {"add": "example.com", "port": 443, "id": "uuid", key: value}
    with pytest.raises(ValueError):
        parser.parse_link(_vmess_link(cfg))


def test_ss_unicode_password_and_percent_encoded_base64_padding():
    from urllib.parse import quote
    password = "пароль@with:colon"
    body = base64.urlsafe_b64encode(f"aes-256-gcm:{password}".encode()).decode()
    result = parser.parse_link(f"ss://{quote(body, safe='')}@[2001:db8::1]:8388")
    assert result["outbound"]["password"] == password


def test_vmess_wrapped_base64_still_parses():
    link = _vmess_link({"add": "example.com", "port": "443", "id": "uuid"})
    result = parser.parse_link(link[:20] + "\n" + link[20:])
    assert result["outbound"]["server_port"] == 443


# --- hysteria2 / hysteria / tuic / anytls ------------------------------------


def test_hysteria2_salamander_and_insecure():
    r = parser.parse_link("hysteria2://pass@example.com:443/?sni=real.example&obfs=salamander"
                          "&obfs-password=ob&insecure=1#hy2")
    assert r["protocol"] == "hysteria2" and r["label"] == "hy2" and r["security"] == "tls"
    assert r["outbound"] == {"type": "hysteria2", "server": "example.com", "server_port": 443, "password": "pass",
                             "tls": {"enabled": True, "server_name": "real.example", "insecure": True},
                             "obfs": {"type": "salamander", "password": "ob"}}


def test_hy2_alias_default_port_and_user_password_auth():
    ob = parser.parse_link("hy2://user:pw@example.com")["outbound"]
    assert ob["type"] == "hysteria2" and ob["server_port"] == 443 and ob["password"] == "user:pw"


@pytest.mark.parametrize("link", ["hysteria2://p@example.com:443,20000-30000/",
                                  "hysteria2://p@example.com:443/?mport=20000-30000"])
def test_hysteria2_port_hopping(link):
    ob = parser.parse_link(link)["outbound"]
    assert ob["server_port"] == 443 and ob["server_ports"] == ["20000:30000"]


def test_hysteria2_ipv6_and_unknown_obfs():
    assert parser.parse_link("hy2://p@[2001:db8::1]:8443")["server"] == "[2001:db8::1]:8443"
    with pytest.raises(ValueError):
        parser.parse_link("hy2://p@example.com:443?obfs=xplus")


@pytest.mark.parametrize("link", ["hysteria2://p@example.com:30000-20000/", "hysteria2://p@example.com:0/"])
def test_hysteria2_rejects_bad_ports(link):
    with pytest.raises(ValueError):
        parser.parse_link(link)


def test_hysteria_v1_defaults_bandwidth_and_alpn():
    ob = parser.parse_link("hysteria://example.com:36712?auth=secret&peer=sni.example&obfsParam=xyz")["outbound"]
    assert ob == {"type": "hysteria", "server": "example.com", "server_port": 36712, "up_mbps": 10, "down_mbps": 50,
                  "tls": {"enabled": True, "server_name": "sni.example", "alpn": ["hysteria"]},
                  "auth_str": "secret", "obfs": "xyz"}


def test_hysteria_v1_rejects_faketcp_and_bad_speed():
    with pytest.raises(ValueError):
        parser.parse_link("hysteria://example.com:36712?protocol=faketcp")
    with pytest.raises(ValueError):
        parser.parse_link("hysteria://example.com:36712?upmbps=fast")


def test_tuic_full_link():
    ob = parser.parse_link("tuic://uuid-1:pass@example.com:443?congestion_control=bbr&udp_relay_mode=quic"
                           "&alpn=h3&allow_insecure=1#t")["outbound"]
    assert ob == {"type": "tuic", "server": "example.com", "server_port": 443, "uuid": "uuid-1", "password": "pass",
                  "tls": {"enabled": True, "server_name": "example.com", "insecure": True, "alpn": ["h3"]},
                  "congestion_control": "bbr", "udp_relay_mode": "quic"}


def test_tuic_requires_uuid_port_and_known_relay_mode():
    for link in ("tuic://example.com:443", "tuic://u:p@example.com", "tuic://u:p@example.com:443?udp_relay_mode=x"):
        with pytest.raises(ValueError):
            parser.parse_link(link)


def test_anytls():
    ob = parser.parse_link("anytls://secret@example.com?sni=s.example")["outbound"]
    assert ob == {"type": "anytls", "server": "example.com", "server_port": 443, "password": "secret",
                  "tls": {"enabled": True, "server_name": "s.example"}}


# --- socks / http ------------------------------------------------------------


@pytest.mark.parametrize("scheme, version", [("socks", "5"), ("socks5", "5"), ("socks5h", "5"),
                                             ("socks4", "4"), ("socks4a", "4a")])
def test_socks_versions(scheme, version):
    r = parser.parse_link(f"{scheme}://1.2.3.4")
    assert r["outbound"] == {"type": "socks", "server": "1.2.3.4", "server_port": 1080, "version": version}
    assert r["security"] == "none"


def test_socks5_credentials_are_percent_decoded():
    ob = parser.parse_link("socks5://us%40er:p%3Ass@1.2.3.4:9050")["outbound"]
    assert (ob["username"], ob["password"], ob["server_port"]) == ("us@er", "p:ss", 9050)


def test_socks4_rejects_password():
    with pytest.raises(ValueError):
        parser.parse_link("socks4://user:pass@1.2.3.4:1080")


def test_http_and_https_proxies():
    plain = parser.parse_link("http://user:pass@proxy.example:3128")["outbound"]
    assert plain == {"type": "http", "server": "proxy.example", "server_port": 3128,
                     "username": "user", "password": "pass"}
    secure = parser.parse_link("https://proxy.example")
    assert secure["outbound"]["server_port"] == 443 and secure["security"] == "tls"
    assert parser.parse_link("http://proxy.example")["outbound"]["server_port"] == 80


# --- распознавание вставленного -----------------------------------------------


def test_link_is_found_inside_a_message():
    text = "Держи сервер 🇩🇪:\nvless://uuid@example.com:443?security=none#DE\nпотом скажешь, как работает"
    r = parser.parse_link(text)
    assert r["protocol"] == "vless" and r["label"] == "DE"


def test_base64_subscription_content_uses_first_link():
    payload = "trojan://p@one.example:443#one\nvless://uuid@two.example:443#two\n"
    r = parser.parse_link(base64.b64encode(payload.encode()).decode())
    assert r["protocol"] == "trojan" and r["label"] == "one"


def test_unknown_scheme_is_named_in_the_error():
    with pytest.raises(ValueError, match="juicity"):
        parser.parse_link("juicity://uuid:pass@example.com:443")


@pytest.mark.parametrize("link", ["tg://socks?server=1.2.3.4&port=1080&user=u&pass=p",
                                  "https://t.me/socks?server=1.2.3.4&port=1080&user=u&pass=p"])
def test_telegram_socks_links(link):
    ob = parser.parse_link(link)["outbound"]
    assert ob == {"type": "socks", "server": "1.2.3.4", "server_port": 1080, "version": "5",
                  "username": "u", "password": "p"}


@pytest.mark.parametrize("link", ["tg://proxy?server=1.2.3.4&port=443&secret=dd00",
                                  "https://t.me/proxy?server=1.2.3.4&port=443&secret=dd00"])
def test_mtproto_points_to_the_telegram_module(link):
    with pytest.raises(ValueError, match="MTProto"):
        parser.parse_link(link)


@pytest.mark.parametrize("link", ["https://sub.example.com/api/v1/client/subscribe?token=abc",
                                  "https://example.com/?token=abc"])
def test_subscription_url_is_not_mistaken_for_https_proxy(link):
    with pytest.raises(ValueError, match="подписк"):
        parser.parse_link(link)


@pytest.mark.parametrize("net", ["xhttp", "splithttp", "kcp"])
def test_xray_only_transports_are_rejected_not_replaced_with_tcp(net):
    with pytest.raises(ValueError, match=net):
        parser.parse_link(f"vless://uuid@example.com:443?security=tls&type={net}")


def test_quic_transport():
    ob = parser.parse_link("vless://uuid@example.com:443?security=tls&type=quic")["outbound"]
    assert ob["transport"] == {"type": "quic"}


def test_ss_plugins():
    link = "ss://YWVzLTI1Ni1nY206cGFzcw@example.com:8388?plugin=simple-obfs%3Bobfs%3Dhttp%3Bobfs-host%3Dcdn.example"
    ob = parser.parse_link(link)["outbound"]
    assert ob["plugin"] == "obfs-local" and ob["plugin_opts"] == "obfs=http;obfs-host=cdn.example"
    with pytest.raises(ValueError, match="kcptun"):
        parser.parse_link("ss://YWVzLTI1Ni1nY206cGFzcw@example.com:8388?plugin=kcptun")


def test_wireguard_link_variants():
    ob = parser.parse_link("wireguard://cHJpdg%3D%3D@example.com:51820?publickey=cHVi&address=10.0.0.2,fd00::2"
                           "&presharedkey=cHNr&reserved=1,2,3&mtu=1280#wg")["outbound"]
    assert ob == {"type": "wireguard", "address": ["10.0.0.2/32", "fd00::2/128"], "private_key": "cHJpdg==",
                  "mtu": 1280, "peers": [{"address": "example.com", "port": 51820, "public_key": "cHVi",
                                          "allowed_ips": ["0.0.0.0/0", "::/0"], "pre_shared_key": "cHNr",
                                          "reserved": [1, 2, 3]}]}
    hiddify = parser.parse_link("wg://example.com:2408?pk=cHJpdg&peer_pk=cHVi&local_address=10.0.0.2/32")
    assert hiddify["server"] == "example.com:2408" and hiddify["outbound"]["private_key"] == "cHJpdg"
    for bad in ("wg://example.com?pk=a", "wg://example.com?pk=a&peer_pk=b",
                "wg://example.com?pk=a&peer_pk=b&ip=10.0.0.2&reserved=1,2"):
        with pytest.raises(ValueError):
            parser.parse_link(bad)


def test_naive_ssh_and_snell():
    naive = parser.parse_link("naive+quic://u:p@example.com")["outbound"]
    assert naive == {"type": "naive", "server": "example.com", "server_port": 443,
                     "tls": {"enabled": True, "server_name": "example.com"}, "username": "u", "password": "p",
                     "quic": True}
    assert parser.parse_link("ssh://example.com")["outbound"] == {"type": "ssh", "server": "example.com",
                                                                   "server_port": 22, "user": "root"}
    snell = parser.parse_link("snell://key@example.com:443?version=3&obfs=tls&obfs-host=cdn.example")["outbound"]
    assert (snell["version"], snell["obfs_mode"], snell["obfs_host"]) == (3, "tls", "cdn.example")


def test_json_outbound_object_list_and_full_config():
    single = parser.parse_link('{"type": "tor", "tag": "my-tor"}')
    assert single["protocol"] == "tor" and single["label"] == "my-tor" and "tag" not in single["outbound"]
    config = {"outbounds": [{"type": "direct", "tag": "direct"},
                            {"type": "vless", "tag": "de", "server": "example.com", "server_port": 443,
                             "uuid": "uuid"}]}
    r = parser.parse_link(json.dumps(config))
    assert r["protocol"] == "vless" and r["server"] == "example.com:443" and r["chain"] == []
    with pytest.raises(ValueError, match="direct"):
        parser.parse_link('[{"type": "direct"}]')
    with pytest.raises(ValueError):
        parser.parse_link('{"type": "vless", "detour": "missing"}')
    with pytest.raises(ValueError):
        parser.parse_link("{not json")
