"""Сайты за Cloudflare: проверка узнаёт его сети, автонастройка проверяет сам Cloudflare.

И «всегда напрямую» решается по стране провайдера, а не по настройкам Windows: в Украине
российские сервисы заблокированы, прямой маршрут их бы сломал.
"""

import threading

import pytest

from modules import cdn, domains
from ui import api as api_mod


@pytest.fixture
def lists(monkeypatch, tmp_path):
    monkeypatch.setattr(domains, "LISTS_DIR", tmp_path)
    domains.save_raw("cloudflare", "speed.cloudflare.com\ncloudflare.com\n104.16.0.0/13\n2606:4700::/32\n")
    return tmp_path


@pytest.mark.parametrize("ip,owner", [
    ("104.21.81.11", "cloudflare"), ("2606:4700::6810:84e5", "cloudflare"),
    ("77.88.55.242", None), (None, None), ("", None), ("не адрес", None),
])
def test_cloudflare_networks_are_recognised(lists, ip, owner):
    assert cdn.provider(ip) == owner


def test_an_edited_list_is_reread_and_a_missing_one_means_nobody(lists):
    assert cdn.provider("8.47.69.1") is None
    domains.save_raw("cloudflare", "8.47.69.0/24\n")
    assert cdn.provider("8.47.69.1") == "cloudflare"
    (lists / "cloudflare.txt").unlink()
    assert cdn.provider("104.21.81.11") is None


def test_a_check_marks_an_address_behind_cloudflare(lists, monkeypatch):
    a = api_mod.Api.__new__(api_mod.Api)
    monkeypatch.setattr(a, "_proxy_socks_addr", lambda domain: None, raising=False)
    answers = {"medium.com": {"target": "medium.com", "status": "blocked", "ip": "104.16.1.1"},
               "ya.ru": {"target": "ya.ru", "status": "ok", "ip": "77.88.55.242"}}
    monkeypatch.setattr(api_mod.blockcheck, "check", lambda domain, socks_addr=None: dict(answers[domain]))
    assert a.block_check_one("medium.com")["data"]["cdn"] == "cloudflare"
    assert "cdn" not in a.block_check_one("ya.ru")["data"]


def test_the_shipped_list_is_checked_by_cloudflares_own_sites():
    from modules.autotune import targets
    assert targets.targets("cloudflare", domains.load_list("cloudflare")) == ["speed.cloudflare.com", "cloudflare.com"]


def test_the_country_is_settled_in_the_background_and_the_page_is_refreshed():
    a = api_mod.Api.__new__(api_mod.Api)
    a._bg_stop = threading.Event()
    settled, poked = [], []
    a._autotune = type("Autotune", (), {"provider": lambda self: {"asn": 1, "name": "x", "country": "UA"}})()
    a.proxy = type("Proxy", (), {"settle_direct_default": lambda self, country: settled.append(country) or True})()
    a.hub = type("Hub", (), {"poke": lambda self, *keys: poked.extend(keys)})()
    a._settle_direct(delay=0)
    assert settled == ["UA"] and poked == ["proxy"]
