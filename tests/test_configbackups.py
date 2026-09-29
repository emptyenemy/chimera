"""Real state setters with isolated files and stubbed process/system operations."""

import json
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
    a.winws.refresh_user_lists = lambda: events.append(("winws_lists", tuple(a.winws.config["lists"]), domains.read_raw("discord")))
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
