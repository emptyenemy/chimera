"""modules/domainrec.py — «записать домены сайта»: разница кэша DNS Windows до и после
открытия сайта, сгруппированная по основному домену. Кэш подставляется, PowerShell не зовётся."""

import pytest

from modules import domainrec
from ui import api as api_mod


@pytest.mark.parametrize("name,expected", [
    ("example.com", "example.com"),
    ("www.example.com", "example.com"),
    ("a.b.cdn.example.com", "example.com"),
    ("shop.co.uk", "shop.co.uk"),
    ("cdn.shop.co.uk", "shop.co.uk"),
    ("news.site.com.au", "site.com.au"),
    ("WWW.Example.COM.", "example.com"),
])
def test_registrable_domain(name, expected):
    assert domainrec.registrable(name) == expected


@pytest.mark.parametrize("name", [
    "localhost", "printer", "nas.local", "router.lan", "wpad", "_ldap._tcp.dc.example.com",
    "1.0.0.127.in-addr.arpa", "192.168.1.5", "::1", "", "co.uk",
])
def test_noise_is_not_a_site(name):
    assert domainrec.registrable(name) is None


def suggest(before, after):
    return domainrec.suggest(set(before), set(after))


def test_new_names_are_grouped_by_registrable_domain():
    got = suggest([], ["www.example.com", "cdn.example.com", "api.other.org"])
    assert [g["domain"] for g in got] == ["example.com", "other.org"]
    assert got[0]["hosts"] == ["cdn.example.com", "www.example.com"]


def test_names_that_were_already_cached_do_not_count():
    got = suggest(["www.example.com", "old.site.net"], ["www.example.com", "old.site.net", "img.example.com"])
    assert [g["domain"] for g in got] == ["example.com"]
    assert got[0]["hosts"] == ["img.example.com"]


def test_trackers_are_flagged_and_sorted_last():
    got = suggest([], ["www.example.com", "stats.doubleclick.net", "mc.yandex.ru", "www.google-analytics.com"])
    assert [g["domain"] for g in got][0] == "example.com"
    flags = {g["domain"]: g["tracker"] for g in got}
    assert flags == {"example.com": False, "doubleclick.net": True, "yandex.ru": True, "google-analytics.com": True}
    assert got[-1]["tracker"] is True


def test_noise_is_dropped_from_the_result():
    got = suggest([], ["nas.local", "1.0.0.127.in-addr.arpa", "wpad", "www.example.com"])
    assert [g["domain"] for g in got] == ["example.com"]


def test_nothing_new_means_empty_result():
    assert suggest(["a.example.com"], ["a.example.com"]) == []


def test_names_are_normalised_before_comparison():
    assert suggest(["WWW.Example.com"], ["www.example.com."]) == []


def test_read_cache_parses_powershell_json(monkeypatch):
    class R:
        returncode, stderr = 0, ""
        stdout = '["A.Example.com","b.example.com","a.example.com"]'
    monkeypatch.setattr(domainrec.subprocess, "run", lambda *a, **k: R())
    assert domainrec.read_cache() == {"a.example.com", "b.example.com"}


def test_read_cache_handles_single_string_and_empty(monkeypatch):
    class One:
        returncode, stderr, stdout = 0, "", '"only.example.com"'

    class Empty:
        returncode, stderr, stdout = 0, "", ""
    monkeypatch.setattr(domainrec.subprocess, "run", lambda *a, **k: One())
    assert domainrec.read_cache() == {"only.example.com"}
    monkeypatch.setattr(domainrec.subprocess, "run", lambda *a, **k: Empty())
    assert domainrec.read_cache() == set()


def test_read_cache_error_is_reported(monkeypatch):
    class Bad:
        returncode, stderr, stdout = 1, "нет доступа", ""
    monkeypatch.setattr(domainrec.subprocess, "run", lambda *a, **k: Bad())
    with pytest.raises(RuntimeError, match="нет доступа"):
        domainrec.read_cache()


# --- Api ---------------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    a = api_mod.Api.__new__(api_mod.Api)
    caches = {"now": {"old.example.com"}}
    flushed = []
    monkeypatch.setattr(domainrec, "read_cache", lambda: set(caches["now"]))
    monkeypatch.setattr(domainrec, "flush", lambda: flushed.append(True))
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    a.caches, a.flushed = caches, flushed
    return a


def test_record_flow_returns_only_new_sites(api):
    started = api.dns_record_start()
    assert started["ok"] and started["data"]["flushed"] is True and api.flushed == [True]

    api.caches["now"] = {"old.example.com", "www.newsite.org", "cdn.newsite.org"}
    res = api.dns_record_stop()

    assert res["ok"]
    assert [d["domain"] for d in res["data"]["domains"]] == ["newsite.org"]


def test_without_admin_rights_cache_is_not_flushed_and_user_is_told(api, monkeypatch):
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    res = api.dns_record_start()
    assert res["data"]["flushed"] is False and api.flushed == []


def test_flush_can_be_declined(api):
    api.dns_record_start(flush=False)
    assert api.flushed == []


def test_stop_without_start_is_an_error(api):
    res = api.dns_record_stop()
    assert res["ok"] is False and "не начата" in res["error"]


def test_result_is_returned_once(api):
    api.dns_record_start()
    api.dns_record_stop()
    assert api.dns_record_stop()["ok"] is False


def test_second_start_replaces_the_first(api):
    api.dns_record_start()
    api.caches["now"] = {"old.example.com", "x.first.org"}
    api.dns_record_start()          # кэш на момент второго старта — новая точка отсчёта
    res = api.dns_record_stop()
    assert res["data"]["domains"] == []
