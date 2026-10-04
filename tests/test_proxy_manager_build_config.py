"""modules/proxy/manager.py — ProxyManager.build_config(): генерация конфига
sing-box для режимов pac/tun на фиктивной ссылке.

STATE_PATH уже изолирован conftest.py (CHIMERA_DATA -> временная папка, миграция
из modules/proxy/state.json отключена), поэтому ProxyManager() тут не читает и
не пишет ничего настоящего. domains.split_lists подменяем monkeypatch'ем, чтобы
не зависеть от содержимого реальных lists/*.txt. download_core/state-пути —
не в этом тесте (см. задание координатора)."""

import pytest

from modules.proxy import manager as proxy_manager
from modules.proxy.manager import (
    DIRECT_DOMAINS_RULESET_PATH, DIRECT_DOMAINS_TAG, DIRECT_IPS_RULESET_PATH, DIRECT_IPS_TAG,
    DOMAINS_RULESET_PATH, DOMAINS_TAG, IPS_RULESET_PATH, IPS_TAG, ProxyManager,
)

# домены и подсети из списков в конфиге — не списком, а ссылкой на файл правил:
# sing-box сам перечитывает такой файл, поэтому правка списка не требует рестарта
DOM_ROUTE = {"rule_set": [DOMAINS_TAG], "outbound": "proxy"}
IP_ROUTE = {"rule_set": [IPS_TAG], "outbound": "proxy"}
DOM_DNS = {"rule_set": [DOMAINS_TAG], "server": "dns-proxy"}
# «всегда напрямую» стоит раньше прокси в любом режиме
DIRECT_ROUTE = {"rule_set": [DIRECT_DOMAINS_TAG, DIRECT_IPS_TAG], "outbound": "direct"}
DIRECT_DNS = {"rule_set": [DIRECT_DOMAINS_TAG], "server": "dns-direct"}
RULE_SETS = [
    {"type": "local", "tag": DOMAINS_TAG, "format": "source", "path": str(DOMAINS_RULESET_PATH)},
    {"type": "local", "tag": IPS_TAG, "format": "source", "path": str(IPS_RULESET_PATH)},
    {"type": "local", "tag": DIRECT_DOMAINS_TAG, "format": "source", "path": str(DIRECT_DOMAINS_RULESET_PATH)},
    {"type": "local", "tag": DIRECT_IPS_TAG, "format": "source", "path": str(DIRECT_IPS_RULESET_PATH)},
]

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

    assert cfg["route"]["rule_set"] == RULE_SETS
    assert cfg["route"]["rules"] == [{"action": "sniff"}, DIRECT_ROUTE, DOM_ROUTE, IP_ROUTE]
    assert cfg["route"]["final"] == "direct"

    # DNS: наши домены идут через прокси-DNS, IP в DNS-правилах не нужны
    assert cfg["dns"]["rules"] == [DIRECT_DNS, DOM_DNS]

    assert cfg["outbounds"][0]["type"] == "vless"
    assert cfg["outbounds"][0]["tag"] == "proxy"
    assert cfg["outbounds"][1] == {"type": "direct", "tag": "direct"}


def test_build_config_pac_mode_without_lists_still_references_rule_sets(pm, monkeypatch):
    # правила ссылаются на файлы всегда, даже пока списки пусты: домен, добавленный
    # позже, попадёт в файл и подхватится без перезапуска ядра
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: ([], []))
    pm.config["link"] = VLESS_LINK
    pm.config["lists"] = []
    pm.config["mode"] = "pac"

    cfg = pm.build_config()
    assert cfg["route"]["rules"] == [{"action": "sniff"}, DIRECT_ROUTE, DOM_ROUTE, IP_ROUTE]
    assert cfg["dns"]["rules"] == [DIRECT_DNS, DOM_DNS]


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
    # список игнорируется в TUN — правил «в прокси» по спискам нет, только «напрямую»
    assert DOM_ROUTE not in cfg["route"]["rules"] and IP_ROUTE not in cfg["route"]["rules"]
    assert _route_rule(cfg["route"], "domain_suffix") is None
    assert _route_rule(cfg["route"], "ip_cidr") is None
    assert cfg["route"]["rule_set"] == RULE_SETS
    private_rule = _route_rule(cfg["route"], "ip_is_private")
    assert private_rule == {"ip_is_private": True, "outbound": "direct"}
    assert cfg["route"]["rules"].index(DIRECT_ROUTE) > cfg["route"]["rules"].index(private_rule)
    assert cfg["dns"]["rules"] == [DIRECT_DNS]
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

    assert cfg["route"]["rule_set"] == RULE_SETS
    assert DOM_ROUTE in rules
    assert IP_ROUTE in rules


def test_build_config_split_mode_dns_proxy_only_for_lists_and_apps(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, ["chrome.exe"])

    assert cfg["dns"]["final"] == "dns-direct"
    assert DOM_DNS in cfg["dns"]["rules"]
    # собственный DNS приложения (async DNS у Chrome) — тоже через прокси
    assert {"process_name": ["chrome.exe"], "server": "dns-proxy"} in cfg["dns"]["rules"]
    assert cfg["route"]["default_domain_resolver"] == {"server": "dns-direct"}


def test_build_config_split_mode_without_apps_has_no_process_rules(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, [])

    assert _route_rule(cfg["route"], "process_name") is None
    assert all("process_name" not in r for r in cfg["dns"]["rules"])
    assert DOM_ROUTE in cfg["route"]["rules"]


def test_build_config_split_mode_without_lists_routes_only_apps(pm, monkeypatch):
    cfg = _split_cfg(pm, monkeypatch, ["WhatsApp.exe"], dom=(), nets=())

    # списки пусты, но ссылки на файлы правил на месте — добавленный домен подхватится сам
    assert DOM_ROUTE in cfg["route"]["rules"]
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
        # IP -> домен помнит только TUN: в PAC ядро видит лишь соединения от браузера с доменом
        assert ("reverse_mapping" in cfg["dns"]) == (mode == "tun")


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


# --- списки применяются на лету: файлы правил, а не рестарт ---------------------------

@pytest.fixture
def rs_paths(tmp_path, monkeypatch):
    dom, ips = tmp_path / "domains.json", tmp_path / "ips.json"
    monkeypatch.setattr(proxy_manager, "DOMAINS_RULESET_PATH", dom)
    monkeypatch.setattr(proxy_manager, "IPS_RULESET_PATH", ips)
    monkeypatch.setattr(proxy_manager, "DIRECT_DOMAINS_RULESET_PATH", tmp_path / "direct-domains.json")
    monkeypatch.setattr(proxy_manager, "DIRECT_IPS_RULESET_PATH", tmp_path / "direct-ips.json")
    return dom, ips


def test_write_rulesets_puts_domains_and_subnets_into_source_files(pm, monkeypatch, rs_paths):
    import json
    monkeypatch.setattr(proxy_manager.domains, "split_lists",
                        lambda names: (["example.com", "foo.example"], ["10.0.0.0/24"]))
    pm.config["lists"] = ["somelist"]
    pm._write_rulesets()

    dom, ips = rs_paths
    assert json.loads(dom.read_text(encoding="utf-8")) == {
        "version": 3, "rules": [{"domain_suffix": ["example.com", "foo.example"]}]}
    assert json.loads(ips.read_text(encoding="utf-8")) == {
        "version": 3, "rules": [{"ip_cidr": ["10.0.0.0/24"]}]}


def test_write_rulesets_empty_lists_use_placeholders_that_match_nothing(pm, monkeypatch, rs_paths):
    # пустое условие в sing-box либо ошибка, либо «подходит всё» — нужна заглушка
    import json
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: ([], []))
    pm._write_rulesets()

    dom, ips = rs_paths
    assert json.loads(dom.read_text(encoding="utf-8"))["rules"] == [
        {"domain_suffix": [proxy_manager.DOMAIN_PLACEHOLDER]}]
    assert json.loads(ips.read_text(encoding="utf-8"))["rules"] == [
        {"ip_cidr": [proxy_manager.IP_PLACEHOLDER]}]


def test_write_rulesets_replaces_files_atomically(pm, monkeypatch, rs_paths):
    # ядро следит за файлом: писать надо целиком и разом, без .tmp-хвостов рядом
    pm.config["lists"] = ["somelist"]
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: (["a.example"], []))
    pm._write_rulesets()
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: (["b.example"], []))
    pm._write_rulesets()

    dom, _ = rs_paths
    assert "b.example" in dom.read_text(encoding="utf-8")
    assert sorted(p.name for p in dom.parent.iterdir()) == ["direct-domains.json", "direct-ips.json",
                                                            "domains.json", "ips.json"]


def _running(monkeypatch, pm):
    monkeypatch.setattr(ProxyManager, "running", property(lambda self: True))
    monkeypatch.setattr(pm, "restart", lambda: pytest.fail("рестарт не нужен — ядро перечитает файлы"))


def test_set_lists_applies_without_restarting_running_proxy(pm, monkeypatch, rs_paths):
    monkeypatch.setattr(proxy_manager.domains, "list_info", lambda: [{"name": "somelist"}])
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: (["example.com"], []))
    _running(monkeypatch, pm)
    pm.config["mode"] = "tun"  # PAC тут не нужен

    pm.set_lists(["somelist"])

    dom, _ = rs_paths
    assert "example.com" in dom.read_text(encoding="utf-8")


def test_reload_lists_in_pac_mode_rewrites_pac_and_refreshes_browsers(pm, monkeypatch, rs_paths):
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: (["example.com"], []))
    _running(monkeypatch, pm)
    calls = []
    monkeypatch.setattr(pm, "_write_pac", lambda: calls.append("pac"))
    monkeypatch.setattr(ProxyManager, "_wininet_refresh", staticmethod(lambda: calls.append("refresh")))
    pm.config["mode"] = "pac"

    pm.reload_lists()

    assert calls == ["pac", "refresh"]


def test_reload_lists_does_nothing_when_proxy_is_stopped(pm, monkeypatch, rs_paths):
    # остановленному прокси файлы допишет start() — трогать диск зря не надо
    monkeypatch.setattr(proxy_manager.domains, "split_lists", lambda names: (["example.com"], []))

    pm.reload_lists()

    dom, ips = rs_paths
    assert not dom.exists() and not ips.exists()


def test_invalid_vmess_json_is_reported_in_state_without_crashing(pm, monkeypatch):
    import base64
    pm.config["link"] = "vmess://" + base64.b64encode(b"[]").decode()
    monkeypatch.setattr(pm, "core_version", lambda: None)
    monkeypatch.setattr(pm, "_split", lambda: ([], []))
    state = pm.state()
    assert state["parsed"] is None
    assert state["error"]


def test_invalid_vmess_port_does_not_replace_saved_link(pm, monkeypatch):
    import base64
    invalid = "vmess://" + base64.b64encode(b'{"add":"example.com","port":443.5,"id":"uuid"}').decode()
    pm.config["link"] = VLESS_LINK
    before = dict(pm.config)
    saved = []
    monkeypatch.setattr(pm, "_save", lambda: saved.append(True))
    with pytest.raises(ValueError):
        pm.set_link(invalid)
    assert pm.config == before
    assert saved == []
