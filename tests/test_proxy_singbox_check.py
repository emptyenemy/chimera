"""Доп. проверка: сгенерированный ProxyManager.build_config() конфиг реально
валиден с точки зрения sing-box (`sing-box check -c`) — для каждого поддержанного
вида ссылки и каждого режима.

`check` — статическая проверка конфига, без запуска ядра (не поднимает TUN,
не слушает порты, не лезет в сеть) — единственная подкоманда sing-box, которую
можно дёргать в тестах без нарушения «не запускать winws2/sing-box». Пишем
конфиг во временный файл, не в реальный singbox-config.json.
Скип, если бинаря нет (bin/sing-box/sing-box.exe — не в репозитории)."""

import json
import subprocess

import pytest

from modules.proxy import manager as proxy_manager
from modules.proxy import parser
from modules.proxy.manager import ProxyManager, SINGBOX_CRONET, SINGBOX_EXE

UUID = "00000000-0000-0000-0000-000000000000"
WG_PRIVATE = "yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk="
WG_PUBLIC = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="
LINKS = {
    "vless-plain": "vless://uuid-1@1.2.3.4:443?security=none&type=tcp#test",
    "vless": f"vless://{UUID}@example.com:443?security=tls&type=ws&path=%2Fws&host=cdn.example#v",
    "vless-quic": f"vless://{UUID}@example.com:443?security=tls&type=quic",
    "trojan": "trojan://pass@example.com:443?type=grpc&serviceName=svc",
    "ss": "ss://YWVzLTI1Ni1nY206cGFzcw@example.com:8388?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dcdn.example",
    "hysteria2": "hysteria2://pass@example.com:443,20000-30000/?sni=example.com&obfs=salamander&obfs-password=x",
    "hysteria": "hysteria://example.com:36712?auth=secret&upmbps=20&downmbps=100",
    "tuic": f"tuic://{UUID}:pass@example.com:443?congestion_control=bbr&udp_relay_mode=native",
    "anytls": "anytls://pass@example.com:443",
    "naive": "naive+https://user:pass@example.com:443",
    "naive-quic": "naive+quic://user:pass@example.com:443",
    "wireguard": f"wireguard://{WG_PRIVATE.replace('+', '%2B').replace('/', '%2F')}@example.com:51820"
                 f"?publickey={WG_PUBLIC.replace('+', '%2B')}&address=10.0.0.2/32,fd00::2&reserved=1,2,3&mtu=1280",
    "ssh": "ssh://root:pass@example.com:22",
    "snell": "snell://psk@example.com:443?version=4&obfs=http&obfs-host=cdn.example",
    "socks5": "socks5://user:pass@1.2.3.4:1080",
    "socks4a": "socks4a://1.2.3.4:1080",
    "http": "http://user:pass@proxy.example:3128",
    "https": "https://user:pass@proxy.example",
    "telegram": "https://t.me/socks?server=1.2.3.4&port=1080&user=u&pass=p",
    "json-shadowtls": json.dumps({"outbounds": [
        {"type": "shadowsocks", "tag": "ss", "method": "2022-blake3-aes-128-gcm", "password": "8JCsPssfgS8tiRwiMlhARg==",
         "detour": "stls"},
        {"type": "shadowtls", "tag": "stls", "server": "example.com", "server_port": 443, "version": 3,
         "password": "x", "tls": {"enabled": True, "server_name": "example.com"}},
        {"type": "direct", "tag": "direct"}]}),
}

pytestmark = pytest.mark.skipif(not SINGBOX_EXE.is_file(), reason="нет bin/sing-box/sing-box.exe")


@pytest.fixture
def pm(monkeypatch):
    monkeypatch.setattr(ProxyManager, "running", property(lambda self: False))
    monkeypatch.setattr(ProxyManager, "_system_pids", staticmethod(lambda: []))
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: (["example.org"], ["10.1.0.0/16"]))
    return ProxyManager()


@pytest.mark.parametrize("mode", ["pac", "split", "tun"])
@pytest.mark.parametrize("kind", sorted(LINKS))
def test_singbox_accepts_generated_config(pm, tmp_path, kind, mode):
    if kind.startswith("naive") and not SINGBOX_CRONET.is_file():
        pytest.skip("naive требует bin/sing-box/libcronet.dll (tools/fetch_bins.py)")
    pm.config.update(link=LINKS[kind], mode=mode, lists=["x"], apps=["Discord.exe", "chrome.exe"])
    # конфиг ссылается на файлы правил — check открывает их и сверяет схему
    pm._write_rulesets()
    config = tmp_path / "singbox-config.json"
    config.write_text(json.dumps(pm.build_config(), ensure_ascii=False), encoding="utf-8")
    result = subprocess.run([str(SINGBOX_EXE), "check", "-c", str(config)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, (result.stderr or result.stdout)[-600:]


def test_wireguard_goes_to_endpoints(pm):
    pm.config.update(link=LINKS["wireguard"], mode="tun")
    config = pm.build_config()
    assert [e["type"] for e in config["endpoints"]] == ["wireguard"] and config["endpoints"][0]["tag"] == "proxy"
    assert config["outbounds"] == [{"type": "direct", "tag": "direct"}]


def test_json_detour_chain_is_kept(pm):
    pm.config.update(link=LINKS["json-shadowtls"], mode="pac")
    tags = [o["tag"] for o in pm.build_config()["outbounds"]]
    assert tags == ["proxy", "stls", "direct"]
    assert parser.parse_link(LINKS["json-shadowtls"])["protocol"] == "shadowsocks"
