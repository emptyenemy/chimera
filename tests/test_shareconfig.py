"""modules/shareconfig.py — обмен конфигом: экспорт по разделам, разбор чужого файла с
белым списком полей, предпросмотр «что изменится», применение со снимком файлов.

Система не трогается: текущее состояние приходит словарём (snapshot), а изменения
делает заглушка ShareOps, которая пишет вызовы."""

import json

from modules import shareconfig as sc


def snapshot():
    """Текущее состояние «у отправителя»: с секретами, которых в экспорте быть не должно."""
    return {
        "lists": {"discord": "discord.com\ndiscord.gg\n", "games": "steamcommunity.com\n", "unused": "x.example\n"},
        "proxy": {"mode": "split", "lists": ["discord"], "apps": ["Discord.exe"],
                  "link": "vless://11111111-2222-3333-4444-555555555555@srv.example:443?security=tls#me",
                  "socks_port": 2080, "autostart": True},
        "hosts": {"assignments": {"xbox": ["games"], "myhosts": ["discord"]},
                  "providers": [{"id": "myhosts", "name": "Мой hosts", "servers": ["203.0.113.5"], "ipv6": [],
                                 "doh": "https://doh.example/dns-query", "dot": "", "filter": False}]},
        "dns": {"providers": [{"id": "mydns", "name": "Мой DNS", "servers": ["9.9.9.10"], "ipv6": [],
                               "doh": "", "dot": "dns.example", "filter": True}]},
        "telegram": {"port": 1443, "host": "0.0.0.0", "secret": "00112233445566778899aabbccddeeff",
                     "advanced": {"disable_secure": False, "fallback_cfproxy": True, "cfproxy_user_domains": ["cf.example"],
                                  "cfproxy_worker_domains": [], "fake_tls_domain": "", "dc_redirects": {"2": "149.154.167.220"},
                                  "proxy_protocol": False, "force_test_dc": False}},
        "winws": {"strategy": "general", "lists": ["discord"], "game": {"mode": "udp", "tcp": "1024-65535", "udp": "1024-65535"},
                  "ipset": "none"},
        "known": {"strategies": ["general", "alt2"], "provider_ids": ["xbox", "comss", "myhosts", "mydns"],
                  "list_names": ["discord", "games", "unused"]},
    }


class Ops:
    """Заглушка изменений: пишет вызовы; fail — сбой на нужной операции."""

    def __init__(self, current=None, fail=None):
        self.current = current or {}
        self.fail, self.calls = fail, []
        self.files = []

    def snapshot(self):
        return self.current

    def _do(self, name, *args):
        self.calls.append((name, *args))
        if self.fail == name:
            raise RuntimeError(f"{name}: сбой")
        return None

    def list_write(self, name, text): return self._do("list_write", name, text)
    def set_proxy(self, mode, lists, apps): return self._do("set_proxy", mode, lists, apps)
    def set_assignments(self, mapping): return self._do("set_assignments", mapping)
    def tg_set_port(self, port): return self._do("tg_set_port", port)
    def tg_set_advanced(self, options): return self._do("tg_set_advanced", options)
    def winws_select(self, sid): return self._do("winws_select", sid)
    def winws_set_lists(self, names): return self._do("winws_set_lists", names)
    def game_set(self, mode, tcp, udp): return self._do("game_set", mode, tcp, udp)
    def ipset_set(self, mode): return self._do("ipset_set", mode)

    def add_provider(self, spec):
        self._do("add_provider", spec["name"])
        return "new-" + spec["id"]

    def backup_files(self, sections, list_names):
        return list(self.files)


def names(ops):
    return [c[0] for c in ops.calls]


# --- экспорт -------------------------------------------------------------------------

def test_default_export_has_portable_sections_only():
    doc = sc.build_export(snapshot(), sc.DEFAULT_SECTIONS, app_version="1.0.0")
    assert doc["schema"] == 1
    assert set(doc["sections"]) == set(sc.DEFAULT_SECTIONS)
    assert "winws" not in doc["sections"]


def test_winws_only_by_explicit_request_and_marked():
    doc = sc.build_export(snapshot(), ["winws"], app_version="1.0.0")
    assert set(doc["sections"]) == {"winws"}
    assert "winws" in sc.PROVIDER_DEPENDENT


def test_export_never_contains_secrets():
    text = json.dumps(sc.build_export(snapshot(), sc.SECTIONS, app_version="1.0.0"), ensure_ascii=False)
    assert "vless://" not in text
    assert "11111111-2222" not in text
    assert "00112233445566778899aabbccddeeff" not in text
    assert "0.0.0.0" not in text        # адрес, на котором слушает Telegram-прокси, — тоже локальное


def test_export_carries_only_referenced_lists():
    doc = sc.build_export(snapshot(), ["proxy", "lists"], app_version="1.0.0")
    assert set(doc["sections"]["lists"]["items"]) == {"discord"}   # proxy ссылается на discord
    assert "unused" not in doc["sections"]["lists"]["items"]


def test_explicit_list_names_override_the_choice():
    doc = sc.build_export(snapshot(), ["lists"], app_version="1.0.0", list_names=["unused", "games"])
    assert set(doc["sections"]["lists"]["items"]) == {"unused", "games"}


def test_min_app_version_follows_export_version():
    assert sc.build_export(snapshot(), ["proxy"], app_version="1.2.3")["min_app_version"] == "1.2.3"
    assert sc.build_export(snapshot(), ["proxy"], app_version="dev")["min_app_version"] is None


# --- разбор чужого файла -----------------------------------------------------------------

def parse(doc_or_text, ours="1.0.0"):
    text = doc_or_text if isinstance(doc_or_text, str) else json.dumps(doc_or_text)
    return sc.parse(text, current_version=ours)


def test_round_trip_keeps_every_section():
    src = sc.build_export(snapshot(), sc.SECTIONS, app_version="1.0.0")
    res = parse(src)
    assert res["error"] is None and res["too_new"] is False
    assert res["doc"]["sections"]["proxy"] == {"mode": "split", "lists": ["discord"], "apps": ["Discord.exe"]}
    assert res["doc"]["sections"]["telegram"]["port"] == 1443
    assert res["doc"]["sections"]["winws"]["strategy"] == "general"
    assert res["unknown_sections"] == [] and res["unknown_fields"] == {}


def test_garbage_is_rejected_with_a_plain_error():
    for text in ("это не json", "[]", "42", '{"schema": "1"}', '{"sections": {}}', ""):
        res = sc.parse(text, current_version="1.0.0")
        assert res["doc"] is None and res["error"], text


def test_newer_schema_is_not_applied():
    res = parse({"schema": 2, "sections": {"proxy": {"mode": "pac"}}})
    assert res["too_new"] is True and "обновите" in res["error"].lower()
    assert res["doc"] is None


def test_min_app_version_newer_than_ours_is_not_applied():
    res = parse({"schema": 1, "min_app_version": "2.0.0", "sections": {"proxy": {"mode": "pac"}}}, ours="1.0.0")
    assert res["too_new"] is True and "2.0.0" in res["error"]


def test_dev_build_is_never_blocked_by_min_version():
    res = parse({"schema": 1, "min_app_version": "9.9.9", "sections": {"proxy": {"mode": "pac"}}}, ours="dev")
    assert res["too_new"] is False and res["doc"]


def test_unknown_sections_and_fields_are_reported_not_applied():
    res = parse({"schema": 1, "sections": {
        "proxy": {"mode": "pac", "lists": [], "apps": [], "wireguard": {"x": 1}},
        "quantum": {"a": 1}}})
    assert res["unknown_sections"] == ["quantum"]
    assert res["unknown_fields"] == {"proxy": ["wireguard"]}
    assert "wireguard" not in res["doc"]["sections"]["proxy"]
    assert "quantum" not in res["doc"]["sections"]


def test_wrong_types_and_values_are_dropped_and_listed():
    res = parse({"schema": 1, "sections": {
        "proxy": {"mode": "vpn", "lists": "discord", "apps": ["../x.exe", "ok.exe", 5]},
        "telegram": {"port": 99999, "advanced": {"disable_secure": "yes"}}}})
    sect = res["doc"]["sections"]
    assert "mode" not in sect["proxy"] and sect["proxy"]["apps"] == ["ok.exe"]
    assert "lists" not in sect["proxy"]
    assert "port" not in sect["telegram"]
    assert res["invalid"], "отброшенное должно быть в списке"


def test_list_names_and_lines_are_sanitised():
    res = parse({"schema": 1, "sections": {"lists": {"items": {
        "../evil": "a.example\n",
        "con/fig": "b.example\n",
        "good": "ok.example\n# комментарий\nbad line with spaces\n1.2.3.0/24\n<script>\n"}}}})
    items = res["doc"]["sections"]["lists"]["items"]
    assert set(items) == {"good"}
    assert items["good"].splitlines() == ["ok.example", "# комментарий", "1.2.3.0/24"]
    assert any("evil" in i for i in res["invalid"])


def test_oversized_list_payload_is_rejected():
    big = {"schema": 1, "sections": {"lists": {"items": {f"l{i}": "a.example\n" * 5000 for i in range(1000)}}}}
    res = sc.parse(json.dumps(big), current_version="1.0.0")
    assert res["doc"] is None and "большой" in res["error"]


def test_provider_fields_are_validated():
    res = parse({"schema": 1, "sections": {"dns": {"providers": [
        {"name": "Норм", "servers": ["9.9.9.10"], "doh": "https://doh.example/dns-query"},
        {"name": "Кривой", "servers": ["not-an-ip"]},
        {"name": "Без адресов"},
        {"name": "Файл", "servers": ["1.1.1.1"], "doh": "file:///c:/x"}]}}})
    got = [p["name"] for p in res["doc"]["sections"]["dns"]["providers"]]
    assert got == ["Норм"]
    assert len(res["invalid"]) == 3


# --- предпросмотр -----------------------------------------------------------------------------

def preview(sections=None, current=None, doc_snapshot=None):
    src = sc.build_export(doc_snapshot or snapshot(), sections or sc.SECTIONS, app_version="1.0.0")
    parsed = parse(src)
    return sc.preview(parsed, current or empty_receiver())


def empty_receiver():
    return {"lists": {}, "proxy": {"mode": "pac", "lists": [], "apps": []},
            "hosts": {"assignments": {}, "providers": []}, "dns": {"providers": []},
            "telegram": {"port": 1443, "advanced": {}},
            "winws": {"strategy": None, "lists": [], "game": {"mode": "off", "tcp": "1024-65535", "udp": "1024-65535"}, "ipset": "none"},
            "known": {"strategies": ["general"], "provider_ids": ["xbox", "comss"], "list_names": []}}


def sec(pv, sid):
    return next(s for s in pv["sections"] if s["id"] == sid)


def test_preview_lists_sections_with_changes():
    pv = preview()
    assert pv["ok"] is True
    assert {s["id"] for s in pv["sections"]} == set(sc.SECTIONS)
    assert any("discord" in c for c in sec(pv, "lists")["changes"])
    assert any("split" in c for c in sec(pv, "proxy")["changes"])


def test_preview_marks_provider_dependent_sections():
    pv = preview()
    assert sec(pv, "winws")["provider_dependent"] is True
    assert sec(pv, "proxy")["provider_dependent"] is False


def test_preview_existing_list_is_merged_not_replaced():
    cur = empty_receiver()
    cur["lists"] = {"discord": "discord.com\nmy-own.example\n"}
    cur["known"]["list_names"] = ["discord"]
    ch = sec(preview(current=cur), "lists")["changes"]
    assert any("добавится 1" in c for c in ch), ch      # discord.gg — новый, discord.com уже есть


def test_preview_foreign_providers_need_confirmation():
    pv = preview()
    assert sec(pv, "hosts")["confirm"], "чужой сервер hosts требует подтверждения"
    assert sec(pv, "dns")["confirm"], "чужой DNS-провайдер требует подтверждения"
    assert pv["needs_confirm"] is True


def test_preview_telegram_relay_domains_need_confirmation():
    pv = preview()
    assert any("cf.example" in c for c in sec(pv, "telegram")["confirm"])


def test_preview_skips_unknown_strategy_and_provider_references():
    src = snapshot()
    src["winws"]["strategy"] = "vanished"
    src["hosts"]["assignments"] = {"unknown-provider": ["discord"]}
    src["hosts"]["providers"] = []
    pv = preview(doc_snapshot=src)
    assert any("vanished" in s for s in sec(pv, "winws")["skipped"])
    assert any("unknown-provider" in s for s in sec(pv, "hosts")["skipped"])


def test_preview_of_unusable_file_is_not_ok():
    pv = sc.preview(sc.parse("мусор", current_version="1.0.0"), empty_receiver())
    assert pv["ok"] is False and pv["error"]


# --- применение ------------------------------------------------------------------------------------

def applied(sections=None, confirmed=False, ops=None, backups=None, list_names=None):
    src = sc.build_export(snapshot(), sections or sc.SECTIONS, app_version="1.0.0", list_names=list_names)
    ops = ops or Ops(current=empty_receiver())
    res = sc.apply(parse(src), sections or list(sc.SECTIONS), confirmed, ops, backup_root=backups)
    return res, ops


def test_apply_unconfirmed_skips_foreign_providers_but_applies_the_rest(tmp_path):
    res, ops = applied(confirmed=False, backups=tmp_path)
    assert "add_provider" not in names(ops)
    assert ("set_proxy", "split", ["discord"], ["Discord.exe"]) in ops.calls
    assert ("tg_set_port", 1443) in ops.calls
    # без подтверждения чужие домены-ретрансляторы Telegram не ставятся, безопасные опции — да
    adv = next(c for c in ops.calls if c[0] == "tg_set_advanced")[1]
    assert "cfproxy_user_domains" not in adv and "disable_secure" in adv
    assert res["skipped"]["hosts"] and res["skipped"]["dns"]


def test_apply_confirmed_adds_providers_and_remaps_assignments(tmp_path):
    res, ops = applied(confirmed=True, backups=tmp_path)
    assert "add_provider" in names(ops)
    mapping = next(c for c in ops.calls if c[0] == "set_assignments")[1]
    # myhosts создан на приёмнике под новым id, привязка переехала на него; xbox — встроенный
    assert mapping == {"xbox": ["games"], "new-myhosts": ["discord"]}


def test_apply_lists_are_written_before_anything_that_references_them(tmp_path):
    _, ops = applied(confirmed=True, backups=tmp_path)
    order = names(ops)
    assert order.index("list_write") < order.index("set_proxy") < order.index("tg_set_port")


def test_apply_merges_into_existing_list(tmp_path):
    cur = empty_receiver()
    cur["lists"] = {"discord": "discord.com\nmy-own.example\n"}
    cur["known"]["list_names"] = ["discord"]
    _, ops = applied(sections=["lists"], ops=Ops(current=cur), backups=tmp_path, list_names=["discord"])
    text = next(c for c in ops.calls if c[0] == "list_write" and c[1] == "discord")[2]
    assert text.splitlines() == ["discord.com", "my-own.example", "discord.gg"]


def test_apply_only_chosen_sections(tmp_path):
    _, ops = applied(sections=["proxy"], backups=tmp_path)
    assert names(ops) == ["set_proxy"]


def test_apply_winws_selects_without_starting(tmp_path):
    _, ops = applied(sections=["winws"], backups=tmp_path)
    assert ("winws_select", "general") in ops.calls
    assert ("game_set", "udp", "1024-65535", "1024-65535") in ops.calls
    assert not any(n.endswith("start") for n in names(ops))


def test_failing_step_is_reported_and_the_rest_continues(tmp_path):
    res, ops = applied(confirmed=True, ops=Ops(current=empty_receiver(), fail="set_proxy"), backups=tmp_path)
    assert any("set_proxy" in e or "proxy" in e for e in res["errors"])
    assert "tg_set_port" in names(ops)


def test_unusable_document_applies_nothing(tmp_path):
    ops = Ops(current=empty_receiver())
    res = sc.apply(sc.parse("мусор", current_version="1.0.0"), ["proxy"], True, ops, backup_root=tmp_path)
    assert ops.calls == [] and res["errors"]


def test_backup_copies_touched_files_and_keeps_last_ten(tmp_path):
    src_file = tmp_path / "state" / "proxy.json"
    src_file.parent.mkdir()
    src_file.write_text('{"mode": "pac"}', encoding="utf-8")
    backups = tmp_path / "backups"
    for _ in range(12):
        ops = Ops(current=empty_receiver())
        ops.files = [src_file]
        res, _ = applied(sections=["proxy"], ops=ops, backups=backups)
        assert res["backup"]
    dirs = sorted(p for p in backups.iterdir() if p.is_dir())
    assert len(dirs) == 10
    assert (dirs[-1] / "proxy.json").read_text(encoding="utf-8") == '{"mode": "pac"}'
    assert all(d.name.endswith("-import") for d in dirs)
