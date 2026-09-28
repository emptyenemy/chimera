"""Api.config_export / config_import_preview / config_import_apply: связка обмена конфигом с
менеджерами. Менеджеры и методы Api — заглушки, модули со списками и провайдерами подменены."""

import json
from types import SimpleNamespace

import pytest

from modules import dns_providers, domains
from modules import shareconfig as sc
from modules.winws import filters
from ui import api as api_mod
from ui import shareops

SECRET_LINK = "vless://11111111-2222-3333-4444-555555555555@srv.example:443?security=tls#me"
TG_SECRET = "00112233445566778899aabbccddeeff"


@pytest.fixture
def api(monkeypatch, tmp_path):
    calls = []
    a = api_mod.Api.__new__(api_mod.Api)
    a.winws = SimpleNamespace(config={"last_strategy": "general", "lists": ["discord"]},
                              strategies=lambda: [{"id": "general"}, {"id": "alt2"}],
                              select_strategy=lambda sid: calls.append(("select_strategy", sid)))
    a.proxy = SimpleNamespace(config={"mode": "split", "lists": ["discord"], "apps": ["Discord.exe"],
                                      "link": SECRET_LINK, "socks_port": 2080})
    a.hosts = SimpleNamespace(assignments=lambda: {"xbox": ["games"]}, providers=lambda: [{"id": "xbox"}])
    a.tg = SimpleNamespace(config={"host": "0.0.0.0", "port": 1443, "secret": TG_SECRET, "autostart": False,
                                   "disable_secure": False, "fallback_cfproxy": True, "cfproxy_user_domains": [],
                                   "cfproxy_worker_domains": [], "fake_tls_domain": "", "dc_redirects": {},
                                   "proxy_protocol": False, "force_test_dc": False})
    ok = {"ok": True, "data": None}
    a.lists_save = lambda name, text: calls.append(("lists_save", name)) or ok
    a.proxy_set_mode = lambda m: calls.append(("proxy_set_mode", m)) or ok
    a.proxy_set_lists = lambda names: calls.append(("proxy_set_lists", names)) or ok
    a.proxy_set_apps = lambda names: calls.append(("proxy_set_apps", names)) or ok
    a.hosts_set_assignments = lambda m: calls.append(("hosts_set_assignments", m)) or ok
    a.tg_set_config = lambda host, port, secret, auto: calls.append(("tg_set_config", host, port, secret, auto)) or ok
    a.tg_set_advanced = lambda o: calls.append(("tg_set_advanced", sorted(o))) or ok
    a.winws_set_lists = lambda n: calls.append(("winws_set_lists", n)) or ok
    a.game_filter_set = lambda m, t, u: calls.append(("game_filter_set", m)) or ok
    a.ipset_set = lambda m: calls.append(("ipset_set", m)) or ok
    a.calls = calls

    monkeypatch.setattr(dns_providers, "load_all", lambda: [
        {"id": "xbox", "name": "XBOX", "servers": ["111.88.96.50"], "unblock": True, "builtin": True},
        {"id": "mydns", "name": "Мой DNS", "servers": ["9.9.9.10"], "doh": "", "dot": "dns.example",
         "ipv6": [], "unblock": False, "builtin": False, "filter": False}])
    lists = {"discord": "discord.com\n", "games": "steamcommunity.com\n"}
    monkeypatch.setattr(domains, "available_lists", lambda: sorted(lists))
    monkeypatch.setattr(domains, "read_raw", lambda n: lists[n])
    monkeypatch.setattr(filters, "game_mode", lambda: "udp")
    monkeypatch.setattr(filters, "game_ranges", lambda: {"tcp": "1024-65535", "udp": "1024-65535"})
    monkeypatch.setattr(filters, "ipset_state", lambda: "none")
    monkeypatch.setattr(shareops.ShareOps, "backup_files", lambda self, sections, names: [])
    return a


def test_export_is_json_without_secrets(api):
    res = api.config_export()
    assert res["ok"] is True
    text = res["data"]
    assert SECRET_LINK not in text and "srv.example" not in text
    assert TG_SECRET not in text and "0.0.0.0" not in text
    doc = json.loads(text)
    assert set(doc["sections"]) == set(sc.DEFAULT_SECTIONS)
    assert doc["sections"]["proxy"]["mode"] == "split"


def test_export_can_include_winws_on_request(api):
    doc = json.loads(api.config_export(["winws"])["data"])
    assert doc["sections"]["winws"]["strategy"] == "general"
    assert doc["sections"]["winws"]["game"]["mode"] == "udp"


def test_export_ignores_unknown_section_names(api):
    doc = json.loads(api.config_export(["proxy", "passwords"])["data"])
    assert list(doc["sections"]) == ["proxy"]


def test_preview_of_own_export_has_nothing_to_break(api):
    text = api.config_export()["data"]
    res = api.config_import_preview(text)
    assert res["ok"] and res["data"]["ok"] is True
    assert {s["id"] for s in res["data"]["sections"]} == set(sc.DEFAULT_SECTIONS)


def test_preview_of_garbage_is_a_result_not_an_exception(api):
    res = api.config_import_preview("это не конфиг")
    assert res["ok"] is True and res["data"]["ok"] is False and res["data"]["error"]


def test_apply_goes_through_the_same_api_methods_as_the_interface(api):
    text = api.config_export(["proxy", "telegram"])["data"]
    res = api.config_import_apply(text, ["proxy", "telegram"])
    assert res["ok"] and res["data"]["errors"] == []
    assert ("proxy_set_mode", "split") in api.calls
    assert ("proxy_set_apps", ["Discord.exe"]) in api.calls
    # порт Telegram ставится с прежними адресом и секретом: свои настройки не теряются
    assert ("tg_set_config", "0.0.0.0", 1443, TG_SECRET, False) in api.calls


def test_apply_winws_selects_strategy_without_touching_the_running_one(api):
    text = api.config_export(["winws"])["data"]
    api.config_import_apply(text, ["winws"])
    assert ("select_strategy", "general") in api.calls
    assert not any(c[0].endswith("start") for c in api.calls)


def test_a_failing_method_is_reported_in_errors(api):
    api.proxy_set_mode = lambda m: {"ok": False, "error": "нужны права администратора"}
    text = api.config_export(["proxy"])["data"]
    res = api.config_import_apply(text, ["proxy"])
    assert res["ok"] and any("администратор" in e for e in res["data"]["errors"])


def test_names_are_reads_or_writes_as_expected():
    assert api_mod.Api.is_read("config_export") is True
    assert api_mod.Api.is_read("config_import_preview") is True
    assert api_mod.Api.is_read("config_import_apply") is False
