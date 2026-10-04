"""Настройки не расходятся с тем, что реально применено, а поле старой версии не ломает снимок.

Выбор списков применяется записью файлов, которые читают winws2 и sing-box. Сорвалась запись —
выбор возвращается: иначе страница показывала бы списки, которых в файлах нет.
"""

import pytest

from modules import configbackups as cb
from modules.errors import ChimeraPermissionError
from modules.proxy import manager as proxy_manager
from modules.winws import manager as winws_manager


def busy(path, *args, **kwargs):
    raise ChimeraPermissionError("err.file.busy", name=getattr(path, "name", "file"))


@pytest.fixture
def lists(monkeypatch):
    from modules import domains
    monkeypatch.setattr(domains, "list_info", lambda: [{"name": "youtube"}, {"name": "discord"}])
    monkeypatch.setattr(domains, "split_lists", lambda names: ([f"{n}.example" for n in names], []))


def test_winws_list_choice_rolls_back_when_its_files_cannot_be_written(tmp_path, monkeypatch, lists):
    monkeypatch.setattr(winws_manager, "STATE_PATH", tmp_path / "winws.json")
    monkeypatch.setattr(winws_manager, "USER_HOSTLIST_PATH", tmp_path / "list-general-user.txt")
    monkeypatch.setattr(winws_manager, "USER_IPSET_PATH", tmp_path / "ipset-user.txt")
    manager = winws_manager.WinwsManager()
    manager.set_lists(["youtube"])
    real = winws_manager.atomic_write_text
    monkeypatch.setattr(winws_manager, "atomic_write_text",
                        lambda path, text: busy(path) if path.name.startswith("list-") else real(path, text))
    with pytest.raises(ChimeraPermissionError):
        manager.set_lists(["youtube", "discord"])
    assert manager.config["lists"] == ["youtube"] and winws_manager.WinwsManager().config["lists"] == ["youtube"]


@pytest.mark.parametrize("setter,key", [("set_lists", "lists"), ("set_direct_lists", "direct_lists")])
def test_proxy_list_choice_rolls_back_when_the_rule_files_cannot_be_written(tmp_path, monkeypatch, lists, setter, key):
    monkeypatch.setattr(proxy_manager, "STATE_PATH", tmp_path / "proxy.json")
    monkeypatch.setattr(proxy_manager.ProxyManager, "running", property(lambda self: True))
    monkeypatch.setattr(proxy_manager.ProxyManager, "_system_pids", staticmethod(lambda: []))
    manager = proxy_manager.ProxyManager()
    before = list(manager.config[key])
    monkeypatch.setattr(manager, "_write_rulesets", lambda: busy(tmp_path / "singbox-domains.json"))
    with pytest.raises(ChimeraPermissionError):
        getattr(manager, setter)(["discord"])
    assert manager.config[key] == before and proxy_manager.ProxyManager().config[key] == before


@pytest.mark.parametrize("sid,raw", [
    ("proxy", {"mode": "tun", "old_field": 1}),
    ("telegram", {"port": 1443, "secret": "a" * 32, "old_field": 1}),
    ("winws", {"lists": ["youtube"], "old_field": 1}),
    ("hosts", {"assignments": {"comss": ["youtube"]}, "enabled": True, "old_field": 1}),
])
def test_a_field_left_from_an_older_version_is_dropped_not_fatal(sid, raw):
    clean = cb.normalize(sid, raw)
    assert "old_field" not in clean


def test_a_dns_provider_field_from_an_older_version_is_dropped_not_fatal():
    provider = {"id": "my-dns", "name": "Мой DNS", "servers": ["1.1.1.1"], "old_field": True}
    assert cb.normalize("dns", [provider])[0]["id"] == "my-dns"


def test_values_are_still_checked_strictly():
    for sid, raw in (("proxy", {"socks_port": 99999}), ("hosts", {"assignments": "все"}), ("winws", {"autostart": "да"})):
        with pytest.raises(ValueError):
            cb.normalize(sid, raw)
