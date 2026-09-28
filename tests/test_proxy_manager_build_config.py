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
def pm(monkeypatch):
    # set_* перезапускают работающий прокси; живой sing-box пользователя (или
    # оставшийся от прошлой сессии) тесты трогать не должны — считаем, что не запущен
    monkeypatch.setattr(ProxyManager, "running", property(lambda self: False))
    monkeypatch.setattr(ProxyManager, "_system_pids", staticmethod(lambda: []))
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


# --- выборочный TUN (mode "split") ------------------------------------------------

def _split_cfg(pm, monkeypatch, apps, dom=("example.com",), nets=("10.0.0.0/24",)):
    monkeypatch.setattr(proxy_manager.domains, "split_lists",
                        lambda names: (list(dom), list(nets)))
    pm.config["link"] = VLESS_LINK
    pm.config["lists"] = ["somelist"] if (dom or nets) else []
    pm.config["apps"] = list(apps)
    pm.config["mode"] = "split"
    return pm.build_config()


def test_build_config_split_mode_is_tun_with_final_direct(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, ["Discord.exe"])

    assert cfg["inbounds"][0]["type"] == "tun"
    assert cfg["route"]["final"] == "direct"
    # процессы ищем, иначе process_name не сработает; DNS запоминает IP -> домен,
    # чтобы соединения без SNI (чат WhatsApp) тоже узнавались по домену
    assert cfg["route"]["find_process"] is True
    assert cfg["dns"]["reverse_mapping"] is True


def test_build_config_split_mode_routes_apps_domains_and_ips_to_proxy(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, ["Discord.exe", "chrome.exe"])
    rules = cfg["route"]["rules"]

    assert rules[0] == {"action": "sniff"}
    assert {"protocol": "dns", "action": "hijack-dns"} in rules
    # локалка — напрямую и раньше правил по приложениям: браузер ходит и на роутер
    private = rules.index({"ip_is_private": True, "outbound": "direct"})
    app_rule = _route_rule(cfg["route"], "process_name")
    assert app_rule == {"process_name": ["Discord.exe", "chrome.exe"], "outbound": "proxy"}
    assert private < rules.index(app_rule)

    assert _route_rule(cfg["route"], "domain_suffix") == {"domain_suffix": ["example.com"], "outbound": "proxy"}
    assert _route_rule(cfg["route"], "ip_cidr") == {"ip_cidr": ["10.0.0.0/24"], "outbound": "proxy"}


def test_build_config_split_mode_dns_proxy_only_for_lists_and_apps(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, ["chrome.exe"])

    assert cfg["dns"]["final"] == "dns-direct"
    assert {"domain_suffix": ["example.com"], "server": "dns-proxy"} in cfg["dns"]["rules"]
    # собственный DNS приложения (async DNS у Chrome) — тоже через прокси
    assert {"process_name": ["chrome.exe"], "server": "dns-proxy"} in cfg["dns"]["rules"]
    assert cfg["route"]["default_domain_resolver"] == {"server": "dns-direct"}


def test_build_config_split_mode_without_apps_has_no_process_rules(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, [])

    assert _route_rule(cfg["route"], "process_name") is None
    assert all("process_name" not in r for r in cfg["dns"]["rules"])
    assert _route_rule(cfg["route"], "domain_suffix") is not None


def test_build_config_split_mode_without_lists_routes_only_apps(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, ["WhatsApp.exe"], dom=(), nets=())

    assert _route_rule(cfg["route"], "domain_suffix") is None
    assert _route_rule(cfg["route"], "ip_cidr") is None
    assert _route_rule(cfg["route"], "process_name")["process_name"] == ["WhatsApp.exe"]


def test_build_config_old_modes_ignore_apps(pm, monkeypatch):
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: (["example.com"], []))
    pm.config["link"] = VLESS_LINK
    pm.config["lists"] = ["somelist"]
    pm.config["apps"] = ["chrome.exe"]
    for mode in ("pac", "tun"):
        pm.config["mode"] = mode
        cfg = pm.build_config()
        assert _route_rule(cfg["route"], "process_name") is None
        assert "find_process" not in cfg["route"]
        assert "reverse_mapping" not in cfg["dns"]


def test_split_mode_is_not_pac_and_needs_admin(pm):
    pm.config["mode"] = "split"
    assert pm.state()["needs_admin"] is True
    assert pm.state()["mode"] == "split"


def test_set_mode_accepts_split_and_rejects_unknown(pm):
    assert pm.set_mode("split")["mode"] == "split"
    with pytest.raises(ValueError):
        pm.set_mode("vpn")


def test_set_apps_dedupes_case_insensitively_and_keeps_names(pm):
    st = pm.set_apps(["Discord.exe", "discord.EXE", " chrome.exe ", "", "WhatsApp.exe"])
    assert st["apps"] == ["Discord.exe", "chrome.exe", "WhatsApp.exe"]
    assert pm.config["apps"] == ["Discord.exe", "chrome.exe", "WhatsApp.exe"]


def test_set_apps_rejects_paths_and_non_exe(pm):
    st = pm.set_apps([r"C:\Program Files\app.exe", "notepad", "ok.exe", "../x.exe"])
    assert st["apps"] == ["ok.exe"]
