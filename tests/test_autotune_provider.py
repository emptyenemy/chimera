"""Карта провайдеров: номер сети, подсказки порядка, отчёт для обсуждений и сборка карты из отчётов."""

import json
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from modules import dataupdate
from modules.autotune import memory, provider, report
from modules.autotune.engine import Engine
from modules.autotune.manager import AutotuneManager
from modules.errors import ChimeraError
from tests.autotune_net import FakeOps, blocked_unless
from tools import provider_map

MGTS = {"asn": 25513, "name": "MGTS", "country": "RU"}
MAP = {"25513": {"name": "MGTS", "services": {"youtube": [
    {"kind": "strategy", "id": "alt", "n": 1}, {"kind": "strategy", "id": "alt2", "n": 4},
    {"kind": "proxy", "id": "proxy", "n": 9}, {"kind": "dns"}]}}}


def ripestat(replies):
    calls = []

    def fetch(endpoint, resource=""):
        calls.append((endpoint, resource))
        reply = replies[endpoint]
        if isinstance(reply, Exception):
            raise reply
        return {"data": reply}
    return fetch, calls


def test_lookup_asks_ripestat_for_the_address_network_holder_and_country():
    fetch, calls = ripestat({"whats-my-ip": {"ip": "203.0.113.7"}, "network-info": {"asns": ["25513"]},
                             "as-overview": {"holder": "MGTS"},
                             "rir-stats-country": {"located_resources": [{"location": "ru"}]}})
    assert provider.lookup(fetch) == MGTS
    assert calls == [("whats-my-ip", ""), ("network-info", "203.0.113.7"), ("as-overview", "AS25513"),
                     ("rir-stats-country", "203.0.113.7")]


def test_an_unknown_country_keeps_the_rest_of_the_answer():
    fetch, _ = ripestat({"whats-my-ip": {"ip": "203.0.113.7"}, "network-info": {"asns": ["25513"]},
                         "as-overview": {"holder": "MGTS"}, "rir-stats-country": OSError("timeout")})
    assert provider.lookup(fetch) == {**MGTS, "country": None}


@pytest.mark.parametrize("replies", [
    {"whats-my-ip": OSError("offline")},
    {"whats-my-ip": {"ip": "203.0.113.7"}, "network-info": {"asns": []}},
    {"whats-my-ip": {"ip": "203.0.113.7"}, "network-info": {"asns": ["0"]}, "as-overview": {}},
])
def test_lookup_gives_up_quietly(replies):
    assert provider.lookup(ripestat(replies)[0]) is None


def test_hints_follow_the_report_count_and_skip_the_proxy(tmp_path):
    path = tmp_path / "map.json"
    path.write_text(json.dumps({"schema": 1, "providers": MAP}), encoding="utf-8")
    assert provider.hints(provider.load_map(path), MGTS) == {
        "youtube": [{"kind": "strategy", "id": "alt2"}, {"kind": "strategy", "id": "alt"}]}
    assert provider.hints(MAP, {"asn": 1, "name": "?"}) == {} and provider.hints(MAP, None) == {}
    path.write_text("{broken", encoding="utf-8")
    assert provider.load_map(path) == {} and provider.load_map(tmp_path / "missing.json") == {}


def youtube_on(strategy):
    return FakeOps({"youtube": ["youtube.com"]}, {"youtube.com": blocked_unless(lambda s: s["strategy"] == strategy)},
                   strategies=("general", "alt", "alt2"), hosts=(), dns_plain=(), dns_unblock=())


def tried(ops):
    return [c[1] for c in ops.calls if c[0] == "apply_strategy"]


def test_what_worked_on_this_network_goes_first_then_the_provider_hints():
    ops = youtube_on("general")
    hints = {"youtube": [{"kind": "strategy", "id": "alt2"}, {"kind": "dns", "id": "alt"}]}
    Engine(ops, memory={"youtube": {"kind": "strategy", "id": "alt"}}, hints=hints).run(["youtube"])
    assert tried(ops)[:3] == ["alt", "alt2", "general"]


@pytest.fixture
def make(tmp_path):
    def build(providers=None):
        ops = youtube_on("alt2")
        ops.providers, ops.provider = providers or {}, MGTS
        mgr = AutotuneManager(ops, tmp_path / "autotune.json", threading.RLock(),
                              memory_path=tmp_path / "memory.json", worker=lambda fn: fn())
        return mgr, ops
    return build


def test_without_a_map_ripestat_is_not_asked(make):
    mgr, ops = make()
    mgr.start()
    assert ops.lookups == 0 and tried(ops)[0] == "general"


def test_with_a_map_the_provider_is_asked_once_per_network_and_its_hints_lead(make, tmp_path):
    mgr, ops = make(MAP)
    mgr.start()
    assert ops.lookups == 1 and tried(ops)[0] == "alt2"
    assert memory.provider("net", tmp_path / "memory.json") == MGTS
    # провайдер — в записи сессии: отчёт после перезапуска программы его не потеряет
    assert json.loads((tmp_path / "autotune.json").read_text(encoding="utf-8"))["provider"] == MGTS
    mgr.keep()
    mgr.start()
    assert ops.lookups == 1


def test_share_builds_a_discussion_form_with_a_machine_readable_line(make):
    mgr, ops = make()
    with pytest.raises(ChimeraError):
        mgr.share()
    mgr.start()
    shared = mgr.share()
    assert ops.lookups == 1     # провайдера узнают по кнопке, если подбор его не спрашивал
    assert "AS25513 · MGTS" in shared["text"] and "| youtube |" in shared["text"]
    query = parse_qs(urlsplit(shared["url"]).query)
    assert shared["url"].startswith(f"https://github.com/{report.REPO}/discussions/new?")
    assert query["category"] == [report.CATEGORY] and query["body"] == [shared["text"]]
    info = report.parse(shared["text"])
    assert info["asn"] == 25513 and info["app"] == "1.1.0" and info["mode"] == "fast"
    assert info["services"]["youtube"] == {"before": ["dpi"], "ok": True, "fix": {"kind": "strategy", "id": "alt2"}}
    mgr.keep()
    assert mgr.share()["text"] == shared["text"]   # и после «Готово» — последний итог


def test_a_report_too_long_for_a_link_is_copied_by_hand(monkeypatch):
    monkeypatch.setattr(report, "URL_LIMIT", 100)
    rec = {"mode": "fast", "provider": None, "report": {"services": []}}
    shared = report.build(rec, {"app": "1.1.0", "data": None})
    assert shared["url"] is None and shared["form"].endswith(f"category={report.CATEGORY}")


@pytest.mark.parametrize("body", ["", "просто текст", "<!-- chimera-report {oops} -->",
                                  '<!-- chimera-report {"v":2,"asn":1,"services":{}} -->',
                                  '<!-- chimera-report {"v":1,"asn":"1","services":{}} -->'])
def test_foreign_or_broken_text_is_not_a_report(body):
    assert report.parse(body) is None


def issue(author, asn, services, when, name="MGTS"):
    line = json.dumps({"v": 1, "asn": asn, "name": name, "services": services})
    return {"number": 1, "author": {"login": author}, "createdAt": when, "body": f"текст\n<!-- chimera-report {line} -->"}


def fixed(kind, sid):
    return {"before": ["dpi"], "ok": True, "fix": {"kind": kind, "id": sid}}


def test_the_map_counts_each_author_once_and_keeps_only_shipped_services():
    issues = [
        issue("ann", 25513, {"youtube": fixed("strategy", "alt")}, "2026-10-01"),
        issue("ann", 25513, {"youtube": fixed("strategy", "alt2")}, "2026-10-02"),   # свежее заменяет старое
        issue("bob", 25513, {"youtube": fixed("strategy", "alt2"), "my-bank": fixed("hosts", "comss"),
                             "discord": {"before": ["dpi"], "ok": False, "fix": {"kind": "strategy", "id": "general"}}},
              "2026-10-03"),
        issue("eve", 25513, {"youtube": fixed("proxy", "proxy")}, "2026-10-03", name="MGTS PJSC"),
        {"number": 9, "author": {"login": "spam"}, "body": "без отчёта"},
    ]
    result = provider_map.build(issues, {"youtube", "discord"}, "2026-10-04")
    assert result == {"schema": 1, "updated": "2026-10-04", "providers": {"25513": {
        "name": "MGTS", "reports": 3, "services": {"youtube": [{"kind": "strategy", "id": "alt2", "n": 2}]}}}}


def test_the_map_ships_with_the_data_update():
    assert dataupdate.is_data_path("strategies/provider-map.json")
    shipped = json.loads(provider.MAP_PATH.read_text(encoding="utf-8"))
    assert shipped["schema"] == 1 and isinstance(shipped["providers"], dict)


def test_no_lookup_while_the_full_tunnel_carries_all_traffic(monkeypatch):
    from ui.autotune import AutotuneOps
    monkeypatch.setattr(provider, "lookup", lambda: MGTS)

    class Proxy:
        running, config = True, {"mode": "tun"}

    ops = AutotuneOps(type("Api", (), {"proxy": Proxy})())
    assert ops.lookup_provider() is None
    Proxy.config = {"mode": "split"}
    assert ops.lookup_provider() == MGTS


def test_reports_are_read_from_every_page_of_the_report_category():
    import json as _json
    from types import SimpleNamespace
    pages = [
        {"pageInfo": {"hasNextPage": True, "endCursor": "c1"},
         "nodes": [{"number": 1, "body": "a", "category": {"slug": report.CATEGORY}},
                   {"number": 2, "body": "b", "category": {"slug": "q-a"}}]},
        {"pageInfo": {"hasNextPage": False, "endCursor": None},
         "nodes": [{"number": 3, "body": "c", "category": {"slug": report.CATEGORY}}]},
    ]
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        page = pages[len(calls) - 1]
        return SimpleNamespace(stdout=_json.dumps({"data": {"repository": {"discussions": page}}}))

    assert [r["number"] for r in provider_map.fetch_reports(run)] == [1, 3]
    assert "after=c1" in calls[1] and not any(a.startswith("after=") for a in calls[0])

