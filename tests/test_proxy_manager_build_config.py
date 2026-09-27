"""modules/proxy/manager.py — ProxyManager.build_config(): генерация конфига
sing-box для режимов pac/tun на фиктивной ссылке.

STATE_PATH уже изолирован conftest.py (CHIMERA_DATA -> временная папка, миграция
из modules/proxy/state.json отключена), поэтому ProxyManager() тут не читает и
не пишет ничего настоящего. domains.split_lists подменяем monkeypatch'ем, чтобы
не зависеть от содержимого реальных lists/*.txt. download_core/state-пути —
не в этом тесте (см. задание координатора)."""

import pytest

from modules.proxy import manager as proxy_manager
from modules.proxy.manager import ProxyManager

VLESS_LINK = "vless://uuid-1@1.2.3.4:443?security=none&type=tcp#test"


@pytest.fixture
def pm():
    return ProxyManager()


def _route_rule(route, key):
    return next((r for r in route["rules"] if key in r), None)


def test_build_config_requires_link(pm):
    with pytest.raises(ValueError, match="ссылка"):
        pm.build_config()


def test_build_config_pac_mode_routes_domains_and_ips_separately(pm, monkeypatch):
    monkeypatch.setattr(
        proxy_manager.domains, "split_lists",
        lambda names: (["example.com", "foo.example"], ["10.0.0.0/24"]),
    )
    pm.config["link"] = VLESS_LINK
    pm.config["lists"] = ["somelist"]
    pm.config["mode"] = "pac"
    pm.config["socks_port"] = 2080

    cfg = pm.build_config()

    assert cfg["inbounds"][0]["type"] == "mixed"
    assert cfg["inbounds"][0]["listen_port"] == 2080

    dom_rule = _route_rule(cfg["route"], "domain_suffix")
    ip_rule = _route_rule(cfg["route"], "ip_cidr")
    assert dom_rule["domain_suffix"] == ["example.com", "foo.example"]
    assert dom_rule["outbound"] == "proxy"
    assert ip_rule["ip_cidr"] == ["10.0.0.0/24"]
    assert ip_rule["outbound"] == "proxy"
    assert cfg["route"]["final"] == "direct"

    # DNS: наши домены идут через прокси-DNS, IP в DNS-правилах не нужны
    assert cfg["dns"]["rules"] == [{"domain_suffix": ["example.com", "foo.example"],
                                     "server": "dns-proxy"}]

    assert cfg["outbounds"][0]["type"] == "vless"
    assert cfg["outbounds"][0]["tag"] == "proxy"
    assert cfg["outbounds"][1] == {"type": "direct", "tag": "direct"}


def test_build_config_pac_mode_without_lists_has_no_route_rules_beyond_sniff(pm, monkeypatch):
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: ([], []))
    pm.config["link"] = VLESS_LINK
    pm.config["lists"] = []
    pm.config["mode"] = "pac"

    cfg = pm.build_config()
    assert cfg["route"]["rules"] == [{"action": "sniff"}]
    assert cfg["dns"]["rules"] == []


def test_build_config_tun_mode_ignores_lists_and_routes_everything_to_proxy(pm, monkeypatch):
    monkeypatch.setattr(
        proxy_manager.domains, "split_lists",
        lambda names: (["example.com"], ["10.0.0.0/24"]),
    )
    pm.config["link"] = VLESS_LINK
    pm.config["lists"] = ["somelist"]
    pm.config["mode"] = "tun"

    cfg = pm.build_config()

    assert cfg["inbounds"][0]["type"] == "tun"
    assert cfg["route"]["final"] == "proxy"
    # список игнорируется в TUN — domain_suffix/ip_cidr правил по спискам нет
    assert _route_rule(cfg["route"], "domain_suffix") is None
    assert _route_rule(cfg["route"], "ip_cidr") is None
    private_rule = _route_rule(cfg["route"], "ip_is_private")
    assert private_rule == {"ip_is_private": True, "outbound": "direct"}
    dns_rule = _route_rule(cfg["route"], "protocol")
    assert dns_rule == {"protocol": "dns", "action": "hijack-dns"}
    assert cfg["dns"]["final"] == "dns-proxy"


def test_build_config_invalid_link_raises_before_touching_lists(pm, monkeypatch):
    called = []
    monkeypatch.setattr(proxy_manager.domains, "split_lists",
                        lambda names: called.append(names) or ([], []))
    pm.config["link"] = "not-a-valid-link"
    pm.config["mode"] = "pac"
    with pytest.raises(ValueError):
        pm.build_config()
