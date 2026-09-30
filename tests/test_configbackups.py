"""Real state setters with isolated files and stubbed process/system operations."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import appconfig, configbackups as cb, dns_providers, domains, i18n, paths
from modules.hosts import manager as hosts_mod
from modules.proxy import manager as proxy_mod
from modules.tgproxy import manager as tg_mod
from modules.winws import filters, manager as winws_mod
from ui import api as api_mod
from ui.shareops import ShareOps

LINK = "vless://11111111-2222-3333-4444-555555555555@server.example:443?security=tls#private"
SECRET = "00112233445566778899aabbccddeeff"


@pytest.fixture
def live(monkeypatch, tmp_path):
    data = tmp_path / "data"
    lists = tmp_path / "lists"
    strategies = tmp_path / "strategies"
    for directory in (data, lists, strategies):
        directory.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(domains, "LISTS_DIR", lists)
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(dns_providers, "USER_PATH", data / "dns_providers.user.json")
    monkeypatch.setattr(proxy_mod, "STATE_PATH", data / "proxy.json")
    monkeypatch.setattr(tg_mod, "STATE_PATH", data / "tgproxy.json")
    monkeypatch.setattr(winws_mod, "STATE_PATH", data / "winws.json")
    monkeypatch.setattr(winws_mod, "STRATEGIES_DIR", strategies)
    monkeypatch.setattr(filters, "IPSET_FILE", strategies / "ipset-all.txt")
    monkeypatch.setattr(filters, "IPSET_BACKUP", strategies / "ipset-all.txt.backup")
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    for sid in ("general", "alt"):
        (strategies / f"{sid}.txt").write_text("--filter-tcp=443\n", encoding="utf-8")
    domains.save_raw("discord", "discord.com\n")
    appconfig.restore_values({"lang": "ru"})
    dns_providers.restore_user([])
    events = []
    a = api_mod.Api.__new__(api_mod.Api)
    a._service_owned = True
    a._smoke = True
    a.push = lambda *args: events.append(("push", *args))
    a.hub = SimpleNamespace(poke=lambda *args: events.append(("poke", *args)))
    a.proxy = proxy_mod.ProxyManager.__new__(proxy_mod.ProxyManager)
    a.proxy.config = {**deepcopy(proxy_mod.DEFAULTS), "link": LINK, "lists": ["discord"]}
    a.proxy.flag = False
    a.proxy.own = True
    a.proxy.fail = False
    a.winws = winws_mod.WinwsManager.__new__(winws_mod.WinwsManager)
    a.winws.config = {**deepcopy(winws_mod.DEFAULTS), "last_strategy": "general", "lists": ["discord"]}
    a.winws.flag = False
    a.winws.own = True
    a.winws._current = "general"
    a.winws.strategies = lambda: [{"id": "general"}, {"id": "alt"}]
    a.tg = tg_mod.TgProxy.__new__(tg_mod.TgProxy)
    a.tg.config = {**deepcopy(tg_mod.DEFAULTS), "secret": SECRET}
    a.tg.flag = False
    monkeypatch.setattr(proxy_mod.ProxyManager, "running", property(lambda self: self.flag))
    monkeypatch.setattr(proxy_mod.ProxyManager, "_ours_alive", property(lambda self: self.own))
    monkeypatch.setattr(winws_mod.WinwsManager, "running", property(lambda self: self.flag))
    monkeypatch.setattr(winws_mod.WinwsManager, "_ours_alive", property(lambda self: self.own))
    monkeypatch.setattr(tg_mod.TgProxy, "running", property(lambda self: self.flag))
    a.proxy.state = lambda: {"running": a.proxy.flag}
    a.winws.state = lambda: {"running": a.winws.flag}
    a.tg.state = lambda: {"running": a.tg.flag}

    def restart_proxy():
        events.append(("proxy_restart", deepcopy(a.proxy.config)))
        a.proxy.flag = False
        if a.proxy.fail:
            a.proxy.fail = False
            raise RuntimeError(LINK)
        a.proxy.flag = True
        return a.proxy.state()

    def start_proxy():
        events.append(("proxy_start",))
        a.proxy.flag = True
        return a.proxy.state()

    def stop_proxy():
        events.append(("proxy_stop",))
        a.proxy.flag = False
        return a.proxy.state()

    def restart_tg():
        events.append(("telegram_restart", deepcopy(a.tg.config)))
        a.tg.flag = True
        return a.tg.state()

    def start_winws(sid):
        events.append(("winws_start", sid))
        a.winws.flag = True
        a.winws._current = sid
        return a.winws.state()

    a.proxy.restart = restart_proxy
    a.proxy.start = start_proxy
    a.proxy.stop = stop_proxy
    a.proxy.reload_lists = lambda: events.append(("proxy_lists", tuple(a.proxy.config["lists"])))
    a.tg.restart = restart_tg
    a.tg.start = restart_tg
    a.winws.start = start_winws
    a.winws.stop = lambda: setattr(a.winws, "flag", False)
    a.winws.refresh_user_lists = lambda: events.append(
        ("winws_lists", tuple(a.winws.config["lists"]),
         domains.read_raw("discord") if "discord" in domains.available_lists() else None))
    a.hosts = hosts_mod.HostsManager(data / "hosts.json", tmp_path / "system-hosts")
    a.hosts._save_state({"assignments": {}, "enabled": False, "entries": []})

    def sync():
        events.append(("hosts_apply", deepcopy(a.hosts._load_state())))
        return {"enabled": a.hosts._load_state().get("enabled")}

    a.hosts._sync = sync
    a.proxy._save()
    a.winws._save()
    a.tg._save()
    ops = ShareOps(a)
    return SimpleNamespace(api=a, ops=ops, root=data / "backups", events=events,
                           data=data, lists=lists, strategies=strategies, tmp=tmp_path)


def full_snapshot(live):
    return {"states": live.ops._current_states(), "lists": {"discord": domains.read_raw("discord")}}


def make_backup(live, states=None, lists=None, kind="import"):
    snapshot = {"states": states or {}, "lists": lists or {}}
    return cb.create_snapshot(snapshot, live.root, kind=kind)


def test_old_flat_import_snapshot_restores_secrets_settings_and_exact_list(live):
    old = live.root / "20260930-120000-001-import"
    old.mkdir(parents=True)
    initial = full_snapshot(live)
    for sid, value in initial["states"].items():
        if sid == "filters":
            continue
        (old / cb.STATE_FILES[sid]).write_text(json.dumps(value), encoding="utf-8")
    (old / "discord.txt").write_text("discord.com\n", encoding="utf-8")
    live.api.proxy.set_mode("split")
    live.api.tg.set_config("0.0.0.0", 2443, "f" * 32, True)
    domains.save_raw("discord", "discord.com\nextra.example\n")
    pv = cb.preview(old.name, live.ops, live.root)
    assert pv["ok"] and pv["secrets_changed"] and pv["warnings"]
    assert LINK not in json.dumps(pv) and SECRET not in json.dumps(pv)
    result = cb.restore(old.name, True, live.ops, live.root)
    assert result["errors"] == [] and cb.load(result["backup"], live.root)
    assert domains.read_raw("discord") == "discord.com\n"
    assert live.api.proxy.config == initial["states"]["proxy"]
    assert live.api.tg.config == initial["states"]["telegram"]


def test_inverse_snapshot_restores_state_before_restore(live):
    first = make_backup(live, {"proxy": {**live.api.proxy.config, "mode": "tun"}}, {"discord": "old.example\n"})
    original = full_snapshot(live)
    result = cb.restore(first, True, live.ops, live.root)
    assert not result["errors"]
    back = cb.restore(result["backup"], True, live.ops, live.root)
    assert not back["errors"] and back["backup"]
    assert live.api.proxy.config == original["states"]["proxy"]
    assert domains.read_raw("discord") == original["lists"]["discord"]
    assert not any(e[0] == "proxy_start" for e in live.events)


def test_import_new_list_snapshot_tracks_absence_and_removes_connections(live):
    doc = json.dumps({"schema": 1, "sections": {"lists": {"items": {"friends": "friend.example\n"}},
                                                  "proxy": {"mode": "pac", "lists": ["friends"]}}})
    imported = live.api.config_import_apply(doc, ["lists", "proxy"])["data"]
    assert imported["errors"] == []
    backup_id = Path(imported["backup"]).name
    assert cb.load(backup_id, live.root)["lists"]["friends"] is None
    assert domains.read_raw("friends") == "friend.example\n"
    result = live.api.config_backup_restore(backup_id, True)["data"]
    assert not result["errors"]
    assert "friends" not in domains.available_lists()
    assert live.api.proxy.config["lists"] == ["discord"]
    inverse = cb.restore(result["backup"], True, live.ops, live.root)
    assert inverse["errors"] == []
    assert domains.read_raw("friends") == "friend.example\n"
    assert live.api.proxy.config["lists"] == ["friends"]


def test_full_restore_updates_already_running_modules_and_no_new_start(live):
    target = full_snapshot(live)
    target["states"]["proxy"].update(mode="split", apps=["Discord.exe"], socks_port=3090)
    target["states"]["telegram"].update(port=2443, fake_tls_domain="example.com")
    target["states"]["winws"]["last_strategy"] = "alt"
    target["states"]["config"]["game_filter"] = "udp"
    target["states"]["hosts"].update(enabled=True, assignments={"cloudflare": ["discord"]})
    target["lists"]["discord"] = "restored.example\n"
    target["states"]["filters"] = {"ipset": "loaded", "content": "192.0.2.0/24\n", "loaded": "198.51.100.0/24\n"}
    backup_id = cb.create_snapshot(target, live.root, kind="import")
    live.api.proxy.flag = live.api.tg.flag = live.api.winws.flag = True
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert not result["errors"] and not result["rollback_errors"]
    assert live.api.proxy.config["socks_port"] == 3090
    assert live.api.tg.config["fake_tls_domain"] == "example.com"
    assert live.api.winws._current == "alt"
    assert filters.ipset_state() == "loaded"
    assert any(e[0] == "proxy_restart" for e in live.events)
    assert any(e[0] == "telegram_restart" for e in live.events)
    assert any(e[:2] == ("winws_start", "alt") for e in live.events)
    assert any(e[0] == "hosts_apply" and e[1]["assignments"] == {"cloudflare": ["discord"]} for e in live.events)
    assert any(e[0] == "winws_lists" and "restored.example" in e[2] for e in live.events)


def test_failed_live_restart_rolls_back_saved_files_and_previously_running_proxy(live):
    backup_id = make_backup(live, {"proxy": {**live.api.proxy.config, "mode": "split"}}, {"discord": "new.example\n"})
    before = deepcopy(live.api.proxy.config)
    live.api.proxy.flag = True
    live.api.proxy.fail = True
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert result["errors"] and result["rolled_back"] and not result["rollback_errors"]
    assert LINK not in json.dumps(result)
    assert live.api.proxy.config == before
    assert live.api.proxy.flag
    assert domains.read_raw("discord") == "discord.com\n"
    assert ("proxy_start",) in live.events
    assert not any(e[0].startswith("telegram") for e in live.events)


def test_failed_rollback_is_reported_and_keeps_inverse_snapshot(live, monkeypatch):
    backup_id = make_backup(live, {"proxy": {**live.api.proxy.config, "mode": "split"}})
    monkeypatch.setattr(live.ops, "restore_snapshot", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(SECRET)))
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert result["errors"] and result["rollback_errors"] and not result["rolled_back"]
    assert cb.load(result["backup"], live.root)["states"]["proxy"]["mode"] == "pac"
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("confirmed", [False, 1, "true"])
def test_confirmation_is_strict_and_no_snapshot_or_mutation_without_it(live, confirmed):
    backup_id = make_backup(live, {"proxy": {**live.api.proxy.config, "mode": "split"}})
    result = cb.restore(backup_id, confirmed, live.ops, live.root)
    assert result["errors"] and result["backup"] is None
    assert live.api.proxy.config["mode"] == "pac"
    assert len(cb.list_backups(live.root)) == 1


def test_admin_refusal_precedes_any_list_write_or_snapshot(live, monkeypatch):
    backup_id = make_backup(live, {"hosts": {"assignments": {}, "enabled": True}}, {"discord": "new.example\n"})
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    assert cb.preview(backup_id, live.ops, live.root)["requires_admin"]
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert result["errors"] and result["backup"] is None
    assert domains.read_raw("discord") == "discord.com\n"
    assert not live.events


@pytest.mark.parametrize("name", ["../20260930-120000-001-import", "C:/outside", "..", "bad", "20261330-120000-001-import"])
def test_untrusted_ids_are_rejected_without_mutation(live, name):
    assert not cb.preview(name, live.ops, live.root)["ok"]
    result = cb.restore(name, True, live.ops, live.root)
    assert result["errors"] and not result["backup"]
    assert not live.events


def test_modified_digest_unknown_file_and_corrupt_json_are_invalid(live):
    backup_id = make_backup(live, {"proxy": live.api.proxy.config})
    directory = live.root / backup_id
    assert cb.list_backups(live.root)[0]["valid"]
    (directory / "proxy.json").write_text('{"link": "' + LINK + '"}', encoding="utf-8")
    assert not cb.preview(backup_id, live.ops, live.root)["ok"]
    assert cb.restore(backup_id, True, live.ops, live.root)["backup"] is None
    assert LINK not in json.dumps(cb.list_backups(live.root))
    (directory / "execute.py").write_text("raise RuntimeError()", encoding="utf-8")
    assert not cb.list_backups(live.root)[0]["valid"]


def test_corrupt_legacy_json_and_unknown_provider_refuse_before_apply(live):
    directory = live.root / "20260930-120000-001-import"
    directory.mkdir(parents=True)
    (directory / "proxy.json").write_text("{", encoding="utf-8")
    assert not cb.preview(directory.name, live.ops, live.root)["ok"]
    (directory / "proxy.json").unlink()
    (directory / "hosts.json").write_text(json.dumps({"assignments": {"unknown": ["discord"]}}), encoding="utf-8")
    result = cb.restore(directory.name, True, live.ops, live.root)
    assert result["errors"] and result["backup"] is None and not live.events


@pytest.mark.parametrize("sid", ["proxy", "winws"])
def test_foreign_running_process_blocks_restore_before_saved_config(live, sid):
    manager = getattr(live.api, sid)
    backup_id = make_backup(live, {sid: manager.config})
    manager.flag = True
    manager.own = False
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert result["errors"] and result["backup"] is None and not live.events


def test_new_import_of_winws_captures_game_config_and_ipset(live):
    initial = filters.ipset_snapshot()
    doc = json.dumps({"schema": 1, "sections": {"winws": {"strategy": "alt", "ipset": "any", "game": {"mode": "udp"}}}})
    result = live.api.config_import_apply(doc, ["winws"])["data"]
    assert result["errors"] == [] and filters.ipset_state() == "any"
    backup_id = Path(result["backup"]).name
    restored = live.api.config_backup_restore(backup_id, True)["data"]
    assert restored["errors"] == []
    assert live.api.winws.config["last_strategy"] == "general"
    assert filters.ipset_snapshot() == initial
    assert appconfig.load().get("game_filter") is None


def test_old_config_frontend_key_is_ignored_and_restart_noted(live):
    directory = live.root / "20260930-120000-001-import"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(json.dumps({"frontend": "legacy", "ui_backend": "browser"}), encoding="utf-8")
    pv = cb.preview(directory.name, live.ops, live.root)
    assert pv["ok"] and len(pv["warnings"]) == 3
    result = cb.restore(directory.name, True, live.ops, live.root)
    assert not result["errors"] and "frontend" not in appconfig.load()


def test_capture_failure_and_oversized_inverse_snapshot_do_not_apply(live, monkeypatch):
    backup_id = make_backup(live, {"proxy": {**live.api.proxy.config, "mode": "split"}})
    monkeypatch.setattr(cb, "MAX_BYTES", 5)
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert result["errors"] and result["backup"] is None
    assert live.api.proxy.config["mode"] == "pac"
    assert not live.events


def test_new_import_captures_in_memory_telegram_secret_if_file_is_absent(live):
    tg_mod.STATE_PATH.unlink()
    doc = json.dumps({"schema": 1, "sections": {"telegram": {"port": 2443}}})
    result = live.api.config_import_apply(doc, ["telegram"])["data"]
    assert not result["errors"]
    backup_id = Path(result["backup"]).name
    assert cb.load(backup_id, live.root)["states"]["telegram"]["secret"] == SECRET
    assert not live.api.config_backup_restore(backup_id, True)["data"]["errors"]
    assert live.api.tg.config["port"] == 1443 and live.api.tg.config["secret"] == SECRET


def test_service_forward_restore_refreshes_only_local_caches(live, monkeypatch):
    live.api._service_owned = False
    live.api.proxy.config["mode"] = "split"
    live.api.winws.config["last_strategy"] = "alt"
    live.api.tg.config["port"] = 2443
    reply = {"restored": ["proxy"], "errors": [], "rollback_errors": [], "rolled_back": False, "backup": "inverse"}
    calls = []
    from modules.cli import client
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    monkeypatch.setattr(client, "connect", lambda: SimpleNamespace(api=lambda *args: calls.append(args) or reply))
    result = live.api.config_backup_restore("20260930-120000-001-import", True)
    assert result["data"] == reply
    assert calls == [("config_backup_restore", "20260930-120000-001-import", True, None)]
    assert live.api.proxy.config["mode"] == "pac"
    assert live.api.winws.config["last_strategy"] == "general"
    assert live.api.tg.config["port"] == 1443
    assert not any(e[0].endswith("start") for e in live.events)
    assert any(e[0] == "push" and e[1] == "langChanged" for e in live.events)


def test_metadata_and_preview_are_localized_and_never_reveal_secrets(live):
    backup_id = make_backup(live, {"telegram": {**live.api.tg.config, "secret": "f" * 32},
                                  "proxy": {**live.api.proxy.config, "link": ""}})
    with i18n.using("en"):
        pv = cb.preview(backup_id, live.ops, live.root)
        assert pv["ok"] and pv["secrets_changed"]
        assert "hidden" in json.dumps(pv)
    result = json.dumps(live.api.config_backups()) + json.dumps(pv)
    assert SECRET not in result and LINK not in result and "f" * 32 not in result


def test_new_methods_have_read_and_system_cli_contracts():
    from modules.cli import registry
    assert api_mod.Api.is_read("config_backups")
    assert api_mod.Api.is_read("config_backup_preview")
    assert not api_mod.Api.is_read("config_backup_restore")
    assert registry.BY_GROUP["config"]["backups"].level == registry.READ
    assert registry.BY_GROUP["config"]["restore-preview"].level == registry.READ
    assert registry.BY_GROUP["config"]["restore"].level == registry.SYSTEM


def test_filters_only_restarts_active_winws_after_files_are_restored(live):
    target = {"ipset": "loaded", "content": "192.0.2.0/24\n", "loaded": "198.51.100.0/24\n"}
    backup_id = make_backup(live, {"filters": target})
    live.api.winws.flag = True
    seen = []
    original = live.api.winws.start
    live.api.winws.start = lambda sid: seen.append(filters.ipset_snapshot()) or original(sid)
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert not result["errors"]
    assert seen == [target]
    inverse = cb.restore(result["backup"], True, live.ops, live.root)
    assert not inverse["errors"] and seen[-1]["content"] is None


@pytest.mark.parametrize("sid", ["filters", "config"])
def test_game_or_ipset_restore_refuses_foreign_winws_before_any_change(live, sid):
    value = ({"ipset": "any", "content": "", "loaded": None} if sid == "filters" else
             {**appconfig.load(), "game_filter": "udp"})
    backup_id = make_backup(live, {sid: value})
    live.api.winws.flag = True
    live.api.winws.own = False
    result = cb.restore(backup_id, True, live.ops, live.root)
    assert result["errors"] and result["backup"] is None and not live.events


def test_cli_json_restore_preview_and_refusal_follow_request_language(live, monkeypatch, capsys):
    from modules.cli import app, commands
    backup_id = make_backup(live, {"proxy": {**live.api.proxy.config, "link": ""}})
    monkeypatch.setattr(commands.Ctx, "call", lambda ctx, method, *args, **kw: getattr(live.api, method)(*args)["data"])
    for lang, word in (("en", "hidden"), ("ru", "скрыто")):
        code = app.main(["--lang", lang, "config", "restore-preview", backup_id, "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0 and payload["level"] == "read" and word in json.dumps(payload, ensure_ascii=False)
        assert LINK not in json.dumps(payload)
    code = app.main(["--lang", "en", "config", "restore", backup_id, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1 and payload["level"] == "system" and "confirmation" in payload["data"]["errors"][0]
    assert live.api.proxy.config["link"] == LINK


def test_cached_hosts_switch_log_does_not_prevent_new_import_snapshot(live):
    state = live.api.hosts._load_state()
    state["switch_log"] = [{"from": "cloudflare", "to": "google", "when": 1}]
    live.api.hosts._save_state(state)
    document = json.dumps({"schema": 1, "sections": {"proxy": {"mode": "split"}}})
    result = live.api.config_import_apply(document, ["proxy"])["data"]
    assert not result["errors"] and result["backup"]
    assert cb.load(Path(result["backup"]).name, live.root)


def test_request_language_does_not_leak_into_other_threads(live):
    from concurrent.futures import ThreadPoolExecutor
    with i18n.request_language("en"), ThreadPoolExecutor(max_workers=1) as pool:
        assert i18n.current_lang() == "en"
        assert pool.submit(i18n.current_lang).result() == "ru"
    assert i18n.current_lang() == "ru"


def test_cli_language_does_not_change_window_language_on_restore(live):
    backup_id = make_backup(live, {"config": {**appconfig.load(), "theme": "dark", "lang": "ru"}})
    reply = live.api.config_backup_restore(backup_id, True, "en")["data"]
    assert not reply["errors"]
    language_events = [e for e in live.events if e[0] == "push" and e[1] == "langChanged"]
    assert language_events[-1][2]["lang"] == "ru"


def test_manual_snapshot_captures_all_settings_and_hides_private_values(live):
    original = full_snapshot(live)
    result = live.api.config_backup_create("en")
    assert result["ok"], result
    entry = result["data"]
    saved = cb.load(entry["id"], live.root)
    assert saved["kind"] == "manual" and saved["complete_lists"]
    assert saved["states"] == original["states"] and saved["lists"] == original["lists"]
    assert entry["sections"] == list(cb.SECTIONS)
    assert not live.events and not live.api.proxy.running and not live.api.winws.running
    assert LINK not in json.dumps(result) and SECRET not in json.dumps(result)
    assert cb.list_backups(live.root)[0]["valid"]


def test_manual_restore_removes_later_lists_and_inverse_recovers_them(live):
    manual = cb.create_manual(live.ops, live.root)["id"]
    domains.save_raw("later", "later.example\n")
    domains.save_raw("discord", "changed.example\n")
    live.api.proxy.set_lists(["later"])
    appconfig.set_value("theme", "light")
    pv = cb.preview(manual, live.ops, live.root)
    assert pv["ok"] and any("later" in text for s in pv["sections"] for text in s["changes"])
    restored = cb.restore(manual, True, live.ops, live.root)
    assert not restored["errors"]
    assert domains.available_lists() == ["discord"]
    assert domains.read_raw("discord") == "discord.com\n"
    assert live.api.proxy.config["lists"] == ["discord"]
    assert appconfig.load()["theme"] == "system"
    undone = cb.restore(restored["backup"], True, live.ops, live.root)
    assert not undone["errors"]
    assert domains.read_raw("later") == "later.example\n"
    assert domains.read_raw("discord") == "changed.example\n"
    assert live.api.proxy.config["lists"] == ["later"]
    assert appconfig.load()["theme"] == "light"


def test_empty_manual_list_inventory_is_preserved_and_restored(live):
    domains.delete_list("discord")
    live.api.proxy.set_lists([])
    live.api.winws.set_lists([])
    entry = cb.create_manual(live.ops, live.root)
    assert "lists" in cb.list_backups(live.root)[0]["sections"]
    assert cb.load(entry["id"], live.root)["lists"] == {}
    domains.save_raw("later", "later.example\n")
    restored = cb.restore(entry["id"], True, live.ops, live.root)
    assert not restored["errors"] and domains.available_lists() == []


@pytest.mark.parametrize("flag", [False, "true", 1, None])
def test_manual_inventory_flag_must_be_a_true_boolean(live, flag):
    entry = cb.create_manual(live.ops, live.root)
    manifest_path = live.root / entry["id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["complete_lists"] = flag
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not cb.preview(entry["id"], live.ops, live.root)["ok"]
    assert not cb.list_backups(live.root)[0]["valid"]


def test_manual_capture_failure_does_not_publish_or_modify_settings(live, monkeypatch):
    before = full_snapshot(live)
    monkeypatch.setattr(ShareOps, "backup_state", lambda *a: (_ for _ in ()).throw(RuntimeError("capture failed")))
    reply = live.api.config_backup_create()
    assert not reply["ok"] and cb.list_backups(live.root) == []
    assert full_snapshot(live) == before and not live.events


def test_manual_capture_is_forwarded_to_the_service_owner(live, monkeypatch):
    from modules.cli import client, commands, registry
    live.api._service_owned = False
    calls = []
    entry = {"id": "20260930-120000-001-manual", "sections": list(cb.SECTIONS)}
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    monkeypatch.setattr(client, "connect", lambda: SimpleNamespace(api=lambda *args: calls.append(args) or entry))
    assert live.api.config_backup_create("en")["data"] == entry
    assert calls == [("config_backup_create", "en")]
    assert cb.list_backups(live.root) == [] and not live.events
    assert not api_mod.Api.is_read("config_backup_create")
    assert registry.BY_GROUP["config"]["backup"].level == registry.APP
    ctx = SimpleNamespace(call=lambda *args: entry)
    result = commands.h_config_backup(ctx, registry.BY_GROUP["config"]["backup"], {})
    assert result.data == entry and entry["id"] in " ".join(result.lines)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows list names are case insensitive")
def test_manual_restore_keeps_a_list_renamed_only_by_case_and_its_inverse(live):
    manual = cb.create_manual(live.ops, live.root)["id"]
    (live.lists / "discord.txt").rename(live.lists / "Discord.txt")
    domains.save_raw("Discord", "changed.example\n")
    assert cb.preview(manual, live.ops, live.root)["ok"]
    restored = cb.restore(manual, True, live.ops, live.root)
    assert not restored["errors"] and domains.read_raw("discord") == "discord.com\n"
    inverse = cb.restore(restored["backup"], True, live.ops, live.root)
    assert not inverse["errors"] and domains.read_raw("discord") == "changed.example\n"


def test_compare_full_snapshots_lists_settings_and_secret_mask(live):
    first = cb.create_manual(live.ops)["id"]
    domains.save_raw("discord", "new.example\n")
    domains.create_list("new-list")
    appconfig.set_value("theme", "light")
    live.api.proxy.config["link"] = LINK.replace("server.example", "other.example")
    second = cb.create_manual(live.ops)["id"]
    before = {p: p.read_bytes() for p in live.tmp.rglob("*") if p.is_file()}
    events = list(live.events)
    result = live.api.config_backup_compare(first, second, "en")["data"]
    assert result["ok"] and not result["identical"] and result["secrets_changed"]
    changes = {s["id"]: s["changes"] for s in result["sections"]}
    assert changes["lists"] == ['Changed contents of list “discord”.', 'Added list “new-list”.']
    assert len(changes["proxy"]) == len(changes["config"]) == 1
    output = json.dumps(result)
    for secret in (LINK, SECRET, "server.example", "other.example", "new.example"):
        assert secret not in output
    assert before == {p: p.read_bytes() for p in live.tmp.rglob("*") if p.is_file()}
    assert events == live.events
    reverse = cb.compare(second, first)
    assert any('Удалён' in c for s in reverse["sections"] for c in s["changes"])


def test_compare_partial_scope_is_unknown_not_deleted(live):
    first = make_backup(live, states={"config": appconfig.load()}, lists={"discord": "discord.com\n"})
    second = make_backup(live, states={"proxy": live.api.proxy.config}, lists={"other": None})
    with i18n.request_language("en"):
        result = cb.compare(first, second)
    assert result["ok"] and not result["identical"]
    changes = [c for s in result["sections"] for c in s["changes"]]
    assert len(changes) == 4
    assert all('not captured' in c for c in changes)
    assert not any('Removed' in c for c in changes)


def test_compare_complete_empty_inventory_and_casefold_line_endings(live):
    first = cb.create_manual(live.ops)["id"]
    second = make_backup(live, lists={"Discord": "discord.com\r\n"})
    result = cb.compare(first, second)
    assert len(result["sections"][0]["changes"]) == 1  # inventory coverage only
    domains.delete_list("discord")
    empty = cb.create_manual(live.ops)["id"]
    result = cb.compare(first, empty)
    assert result["ok"]
    assert any('discord' in c for s in result["sections"] if s["id"] == "lists" for c in s["changes"])
    assert cb.compare(empty, empty)["identical"]


def test_compare_explicit_list_absence_and_provider_changes(live):
    provider = {"id": "custom", "name": "Custom", "servers": ["1.1.1.1"]}
    first = make_backup(live, states={"dns": [provider]}, lists={"discord": None})
    second = make_backup(live, states={"dns": [{**provider, "servers": ["8.8.8.8"]}]}, lists={"discord": "discord.com\n"})
    with i18n.request_language("en"):
        result = cb.compare(first, second)
    assert [s["id"] for s in result["sections"]] == ["lists", "dns"]
    assert result["sections"][0]["changes"] == ['Added list “discord”.']
    assert result["sections"][1]["changes"] == ['Changed settings of provider custom.']
    assert '8.8.8.8' not in json.dumps(result)


def test_compare_invalid_digest_and_path_ids_redact_errors(live):
    first = make_backup(live, states={"proxy": live.api.proxy.config})
    assert cb.compare(first, first)["identical"]
    (live.root / first / "proxy.json").write_text(LINK)
    for other in (first, "../../" + SECRET, None, []):
        result = cb.compare(first, other)
        assert not result["ok"] and result["errors"] and not result["sections"]
        assert SECRET not in json.dumps(result) and LINK not in json.dumps(result)


def test_compare_is_read_forwards_owner_and_cli_reports_failures(live, monkeypatch):
    from modules.cli import client, commands, registry
    calls = []
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    live.api._service_owned = False
    remote = {"ok": True, "left_id": "first", "right_id": "second", "identical": True, "sections": [], "errors": []}
    monkeypatch.setattr(client, "connect", lambda: SimpleNamespace(api=lambda *args: calls.append(args) or remote))
    assert live.api.config_backup_compare("first", "second", "en")["data"] == remote
    assert calls == [("config_backup_compare", "first", "second", "en")]
    assert api_mod.Api.is_read("config_backup_compare")
    action = registry.BY_GROUP["config"]["compare"]
    assert action.level == registry.READ
    ctx = SimpleNamespace(call=lambda *args: remote)
    assert commands.h_config_compare(ctx, action, {"a0": "first", "a1": "second"}).exit_code == 0
    remote.update(ok=False, identical=False, errors=["Invalid snapshot"])
    assert commands.h_config_compare(ctx, action, {"a0": "first", "a1": "second"}).exit_code == 1


@pytest.mark.parametrize("method,args,section", [
    ("config_set", ("theme", "light"), "config"),
    ("proxy_set_link", (LINK.replace("server.example", "new.example"),), "proxy"),
    ("proxy_set_lists", ([],), "proxy"),
    ("proxy_set_apps", (["Discord.exe"],), "proxy"),
    ("proxy_set_autostart", (True,), "proxy"),
    ("proxy_set_mode", ("tun",), "proxy"),
    ("winws_set_lists", ([],), "winws"),
    ("winws_set_autostart", (True,), "winws"),
    ("tg_set_config", ("localhost", 2443, SECRET, True), "telegram"),
    ("tg_set_advanced", ({"fake_tls_domain": "example.com"},), "telegram"),
    ("tg_regen_secret", (), "telegram"),
    ("hosts_set_enabled", (True,), "hosts"),
    ("hosts_set_background", ({"refresh_enabled": False},), "hosts"),
    ("game_filter_set", ("tcp", "80,443", None), "config"),
    ("ipset_set", ("none",), "filters"),
])
def test_auto_snapshot_captures_old_settings_and_restores(live, method, args, section):
    old = live.ops._current_states()[section]
    reply = getattr(live.api, method)(*args)
    assert reply["ok"], reply.get("error")
    backups = cb.list_backups(live.root)
    assert len(backups) == 1 and backups[0]["kind"] == "auto" and backups[0]["valid"]
    backup = cb.load(backups[0]["id"], live.root)
    assert backup["states"][section] == old
    assert not cb.restore(backup["id"], True, live.ops)["errors"]
    assert live.ops._current_states()[section] == old


def test_auto_is_persisted_before_setter_and_failure_blocks_change(live, monkeypatch):
    original = appconfig.set_value
    def checked(key, value):
        backups = cb.list_backups(live.root)
        assert len(backups) == 1 and cb.load(backups[0]["id"])["states"]["config"]["theme"] == "system"
        return original(key, value)
    monkeypatch.setattr(appconfig, "set_value", checked)
    assert live.api.config_set("theme", "light")["ok"]
    before = full_snapshot(live)
    monkeypatch.setattr(cb, "create_snapshot", lambda *a, **k: (_ for _ in ()).throw(OSError(SECRET)))
    reply = live.api.config_set("theme", "dark")
    assert not reply["ok"] and reply["code"] == "err.backup.prepare_failed"
    assert SECRET not in json.dumps(reply)
    assert full_snapshot(live) == before


def test_noop_and_invalid_operations_preserve_existing_backup_history(live, monkeypatch):
    monkeypatch.setattr(cb, "KEEP", 2)
    first = cb.create_manual(live.ops)["id"]
    second = cb.create_manual(live.ops)["id"]
    before = {p: p.read_bytes() for p in live.root.rglob("*") if p.is_file()}
    for _ in range(3):
        assert live.api.config_set("theme", "system")["ok"]
        assert not live.api.config_set("theme", "neon")["ok"]
        assert live.api.lists_save("discord", "discord.com\n")["ok"]
    assert before == {p: p.read_bytes() for p in live.root.rglob("*") if p.is_file()}
    assert {b["id"] for b in cb.list_backups()} == {first, second}


def test_failed_setter_with_partial_change_keeps_its_inverse(live):
    before = appconfig.load()
    reply = live.api.game_filter_set("tcp", "invalid", None)
    assert not reply["ok"]
    assert appconfig.load()["game_filter"] == "tcp"
    backup = cb.list_backups()[0]
    assert cb.load(backup["id"])["states"]["config"] == before
    assert not cb.restore(backup["id"], True, live.ops)["errors"]
    assert appconfig.load() == before


@pytest.mark.parametrize("method,args", [
    ("lists_create", ("new-list",)),
    ("lists_save", ("new-list", "new.example\n")),
    ("lists_delete", ("discord",)),
    ("lists_rename", ("discord", "renamed")),
])
def test_auto_list_inventory_changes_restore_connections(live, method, args):
    old = full_snapshot(live)
    assert getattr(live.api, method)(*args)["ok"]
    backups = cb.list_backups()
    assert len(backups) == 1
    assert not cb.restore(backups[0]["id"], True, live.ops)["errors"]
    assert domains.available_lists() == ["discord"]
    assert full_snapshot(live) == old


def test_auto_provider_add_and_delete_restore_related_hosts(live):
    assert live.api.hosts_add_provider("Local", "", ["1.1.1.1"])["ok"]
    backup = cb.list_backups()[0]
    assert set(cb.load(backup["id"])["states"]) == {"dns", "hosts"}
    provider = next(p for p in dns_providers.load_all() if not p.get("builtin"))
    live.api.hosts._save_state({"assignments": {provider["id"]: ["discord"]}, "enabled": False})
    assert live.api.hosts_delete_provider(provider["id"])["ok"]
    deleted = cb.list_backups()[0]
    assert not cb.restore(deleted["id"], True, live.ops)["errors"]
    assert live.api.hosts.assignments() == {provider["id"]: ["discord"]}


def test_restore_and_import_do_not_create_nested_auto_snapshots(live):
    backup = cb.create_manual(live.ops)["id"]
    assert live.api.config_set("theme", "light")["ok"]
    count = len(cb.list_backups())
    assert not live.api.config_backup_restore(backup, True)["data"]["errors"]
    assert len(cb.list_backups()) == count + 1
    portable = {"schema": 1, "sections": {"lists": {"discord": "different.example\n"}, "proxy": {"mode": "tun"}}}
    count = len(cb.list_backups())
    reply = live.api.config_import_apply(json.dumps(portable), ["lists", "proxy"], True)
    assert reply["ok"] and not reply["data"]["errors"]
    assert len(cb.list_backups()) == count + 1
    assert cb.list_backups()[0]["kind"] == "import"


def test_auto_forwarding_service_creates_only_owner_snapshot(live, monkeypatch):
    from modules.cli import client
    owner = live.api
    ui = api_mod.Api.__new__(api_mod.Api)
    ui._service_owned = False
    ui.proxy, ui.winws, ui.tg = owner.proxy, owner.winws, owner.tg
    calls = []
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    def remote(method, *args):
        calls.append((method, args))
        reply = getattr(owner, method)(*args)
        assert reply["ok"]
        return reply["data"]
    monkeypatch.setattr(client, "connect", lambda: SimpleNamespace(api=remote))
    assert ui.config_set(key="theme", value="light")["ok"]
    assert calls == [("config_set", ("theme", "light"))]
    assert len(cb.list_backups()) == 1


def test_offline_cli_config_and_lists_use_automatic_snapshots(live, monkeypatch):
    from modules.cli import client, commands, registry
    monkeypatch.setattr(client, "discover", lambda: None)
    ctx = commands.Ctx()
    action = registry.BY_GROUP["config"]["set"]
    commands.h_config_set(ctx, action, {"a0": "theme", "a1": "light"})
    config_backup = cb.list_backups()[0]
    assert cb.load(config_backup["id"])["states"]["config"]["theme"] == "system"
    ctx.call_or_local("lists_save", ("discord", "changed.example\n"), lambda: domains.save_raw("discord", "changed.example\n"))
    lists_backup = cb.list_backups()[0]
    assert cb.load(lists_backup["id"])["lists"] == {"discord": "discord.com\n"}
    assert not cb.restore(lists_backup["id"], True, live.ops)["errors"]
    assert domains.read_raw("discord") == "discord.com\n"


def test_history_uses_numeric_sequence_after_999(live, monkeypatch):
    monkeypatch.setattr(cb, "KEEP", 2)
    frozen = cb.datetime.now(cb.UTC)
    class FixedDateTime(cb.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz)
    monkeypatch.setattr(cb, "datetime", FixedDateTime)
    first = cb.create_manual(live.ops)["id"]
    renamed = first.rsplit("-", 2)[0] + "-999-manual"
    (live.root / first).rename(live.root / renamed)
    second = cb.create_manual(live.ops)["id"]
    assert "-1000-" in second
    assert live.api.config_set("theme", "light")["ok"]
    entries = cb.list_backups()
    assert len(entries) == 2 and "-1001-auto" in entries[0]["id"]
    assert entries[1]["id"] == second
    assert not (live.root / renamed).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows list names are case insensitive")
def test_auto_case_only_list_rename_creates_a_valid_inverse(live):
    with cb.automatic(lambda: live.ops.backup_state(("proxy", "winws", "hosts"), ("discord", "Discord"))):
        (live.lists / "discord.txt").rename(live.lists / "Discord.txt")
        domains.save_raw("Discord", "changed.example\n")
    entry = cb.list_backups()[0]
    assert entry["valid"] and cb.load(entry["id"])["lists"] == {"discord": "discord.com\n"}
    assert not cb.restore(entry["id"], True, live.ops)["errors"]
    assert live.api.proxy.config["lists"] == ["discord"]


def test_auto_cleanup_failure_does_not_report_a_successful_change_as_failed(live, monkeypatch):
    logs = []
    monkeypatch.setattr(cb.applog, "write", lambda text: logs.append(text))
    monkeypatch.setattr(cb, "_prune", lambda *a: (_ for _ in ()).throw(PermissionError("busy")))
    assert live.api.config_set("theme", "light")["ok"]
    assert appconfig.load()["theme"] == "light"
    assert cb.list_backups()[0]["valid"] and len(logs) == 1


def test_auto_read_commands_do_not_capture(live, monkeypatch):
    monkeypatch.setattr(cb, "create_snapshot", lambda *a, **k: pytest.fail("Read attempted a snapshot"))
    assert live.api.config_read()["ok"]
    assert live.api.config_backups()["data"] == []
    assert live.api.lists_read("discord")["ok"]
    assert not live.api.config_backup_compare("missing", "missing")["data"]["ok"]
