"""«Всегда напрямую»: списки, которые идут мимо прокси в любом режиме, даже в полном TUN."""

import json

import pytest

from modules import domains, liveapply
from modules.proxy import manager as proxy_manager
from modules.proxy.manager import DIRECT_DOMAINS_TAG, DIRECT_IPS_TAG, DOMAINS_TAG, ProxyManager

VLESS = "vless://uuid-1@1.2.3.4:443?security=none&type=tcp#test"
DIRECT_ROUTE = {"rule_set": [DIRECT_DOMAINS_TAG, DIRECT_IPS_TAG], "outbound": "direct"}
DIRECT_DNS = {"rule_set": [DIRECT_DOMAINS_TAG], "server": "dns-direct"}


@pytest.fixture
def lists_dir(monkeypatch, tmp_path):
    folder = tmp_path / "lists"
    folder.mkdir()
    monkeypatch.setattr(domains, "LISTS_DIR", folder)
    for name, text in {"youtube": "youtube.com\n", "banks": "sberbank.ru\n10.20.0.0/16\n",
                       "gov": "gosuslugi.ru\n"}.items():
        domains.save_raw(name, text)
    return folder


@pytest.fixture
def pm(monkeypatch, tmp_path, lists_dir):
    monkeypatch.setattr(proxy_manager, "STATE_PATH", tmp_path / "proxy.json")
    for attr in ("DOMAINS_RULESET_PATH", "IPS_RULESET_PATH", "DIRECT_DOMAINS_RULESET_PATH", "DIRECT_IPS_RULESET_PATH"):
        monkeypatch.setattr(proxy_manager, attr, tmp_path / f"{attr.lower()}.json")
    monkeypatch.setattr(ProxyManager, "running", property(lambda self: False))
    monkeypatch.setattr(ProxyManager, "_system_pids", staticmethod(lambda: []))
    manager = ProxyManager()
    manager.config.update(link=VLESS, lists=["youtube"], direct_lists=["banks"])
    return manager


def _rules(path):
    return json.loads(path.read_text(encoding="utf-8"))["rules"]


@pytest.mark.parametrize("mode", ["pac", "split", "tun"])
def test_direct_lists_win_over_the_proxy_in_every_mode(pm, mode):
    pm.config.update(mode=mode, apps=["chrome.exe"])
    cfg = pm.build_config()
    rules = cfg["route"]["rules"]
    first_proxy = next(i for i, r in enumerate(rules) if r.get("outbound") == "proxy") if mode != "tun" else len(rules)
    assert rules.index(DIRECT_ROUTE) < first_proxy
    assert cfg["route"]["final"] == ("proxy" if mode == "tun" else "direct")
    # банк резолвится своим DNS и тогда, когда весь остальной DNS идёт через прокси
    assert cfg["dns"]["rules"][0] == DIRECT_DNS
    tags = {r["tag"] for r in cfg["route"]["rule_set"]}
    assert {DIRECT_DOMAINS_TAG, DIRECT_IPS_TAG, DOMAINS_TAG} <= tags


def test_rule_files_hold_only_the_direct_lists(pm):
    pm._write_rulesets()
    assert _rules(proxy_manager.DIRECT_DOMAINS_RULESET_PATH) == [{"domain_suffix": ["sberbank.ru"]}]
    assert _rules(proxy_manager.DIRECT_IPS_RULESET_PATH) == [{"ip_cidr": ["10.20.0.0/16"]}]
    assert _rules(proxy_manager.DOMAINS_RULESET_PATH) == [{"domain_suffix": ["youtube.com"]}]


def test_a_missing_or_empty_direct_list_leaves_a_placeholder(pm, lists_dir):
    pm.config["direct_lists"] = ["deleted"]
    pm._write_rulesets()
    assert _rules(proxy_manager.DIRECT_DOMAINS_RULESET_PATH) == [{"domain_suffix": [proxy_manager.DOMAIN_PLACEHOLDER]}]
    assert _rules(proxy_manager.DIRECT_IPS_RULESET_PATH) == [{"ip_cidr": [proxy_manager.IP_PLACEHOLDER]}]


def test_set_direct_lists_keeps_known_names_and_applies_them(pm, monkeypatch):
    reloads = []
    monkeypatch.setattr(pm, "reload_lists", lambda: reloads.append(True))
    state = pm.set_direct_lists(["gov", "nope", "banks"])
    assert state["direct_lists"] == ["gov", "banks"] and reloads == [True]
    assert json.loads(proxy_manager.STATE_PATH.read_text(encoding="utf-8"))["direct_lists"] == ["gov", "banks"]
    assert pm.set_direct_lists(None)["direct_lists"] == []


def test_old_settings_get_the_shipped_list(monkeypatch, tmp_path, lists_dir):
    state = tmp_path / "proxy.json"
    state.write_text(json.dumps({"link": "", "lists": ["youtube"]}), encoding="utf-8")
    monkeypatch.setattr(proxy_manager, "STATE_PATH", state)
    monkeypatch.setattr(ProxyManager, "_system_pids", staticmethod(lambda: []))
    assert ProxyManager().config["direct_lists"] == ["russia-direct"]


def test_shipped_list_is_valid_and_not_offered_to_autotune():
    from ui.autotune import AutotuneOps
    assert domains.validate_list("russia-direct")["ok"]

    class Api:
        class proxy:
            config = {"direct_lists": ["russia-direct"]}

    names = [s["name"] for s in AutotuneOps(Api()).services()]
    assert "russia-direct" not in names and "youtube" in names


class Proxy:
    def __init__(self):
        self.config = {"lists": [], "direct_lists": ["banks"]}
        self.calls = []

    def reload_lists(self):
        self.calls.append("reload")

    def set_lists(self, names):
        self.calls.append(("set_lists", list(names)))

    def set_direct_lists(self, names):
        self.calls.append(("set_direct_lists", list(names)))


class Idle:
    config = {"lists": []}

    def assignments(self):
        return {}


def test_editing_a_direct_list_reloads_the_proxy_and_deleting_it_drops_it():
    proxy = Proxy()
    assert liveapply.consumers(["Banks"], Idle(), proxy, Idle()) == ["proxy"]
    liveapply.lists_changed(["banks"], Idle(), proxy, Idle())
    liveapply.lists_removed("banks", Idle(), proxy, Idle())
    assert proxy.calls == ["reload", ("set_lists", []), ("set_direct_lists", ["banks"])]


def test_backup_rejects_a_malformed_direct_list_value():
    from modules import configbackups as cb
    assert cb.normalize("proxy", {"direct_lists": ["banks"]})["direct_lists"] == ["banks"]
    for bad in ("banks", [1], ["../evil"]):
        with pytest.raises(Exception):
            cb.normalize("proxy", {"direct_lists": bad})
