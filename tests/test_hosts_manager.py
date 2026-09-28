"""modules/hosts/manager.py — сборка/снятие блока между маркерами
# >>> chimera-hosts >>> / # <<< chimera-hosts <<< и синхронизация с привязками.

HostsManager принимает state_path/hosts_path в конструкторе — используем
временные файлы вместо системного hosts и state.json. Реальный резолвинг DNS
(resolve_domains, сеть) и is_admin() (реальные права) подменяем monkeypatch'ем:
никакой сети и никакого системного hosts тут не открывается.
"""

import json

import pytest

from modules.hosts import manager as hosts_manager
from modules.hosts.manager import BEGIN_MARK, END_MARK, HostsManager


@pytest.fixture
def hm(tmp_path, monkeypatch):
    hosts_path = tmp_path / "hosts"
    hosts_path.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    # ipconfig /flushdns — реальный системный вызов, гасим его в _write_hosts
    monkeypatch.setattr(hosts_manager.subprocess, "run", lambda *a, **kw: None)
    return HostsManager(state_path=state_path, hosts_path=hosts_path)


def test_state_defaults_when_no_state_file(hm):
    st = hm.state()
    assert st == {
        "applied": False, "enabled": True, "assignments": {}, "count": 0,
        "health": None, "last_switch": None,
        "background": {
            "refresh_enabled": True, "refresh_interval": 6 * 3600,
            "check_enabled": True, "check_interval": 15 * 60,
            "autoswitch_enabled": False, "provider_order": [],
        },
    }


def test_write_block_inserts_marked_section(hm):
    hm._write_block([("Xbox DNS", [{"ip": "1.2.3.4", "host": "example.com"}])])
    text = hm.hosts_path.read_text(encoding="utf-8")
    assert BEGIN_MARK in text
    assert END_MARK in text
    assert "# Xbox DNS" in text
    assert "1.2.3.4 example.com" in text
    assert "127.0.0.1 localhost" in text  # старое содержимое hosts не тронуто
    assert hm._is_applied()


def test_write_block_replaces_previous_block_not_duplicates(hm):
    hm._write_block([("A", [{"ip": "1.1.1.1", "host": "a.example"}])])
    hm._write_block([("B", [{"ip": "2.2.2.2", "host": "b.example"}])])
    text = hm.hosts_path.read_text(encoding="utf-8")
    assert text.count(BEGIN_MARK) == 1
    assert text.count(END_MARK) == 1
    assert "a.example" not in text
    assert "b.example" in text


def test_write_block_groups_multiple_providers(hm):
    hm._write_block([
        ("Xbox DNS", [{"ip": "1.1.1.1", "host": "a.example"}]),
        ("Comss", [{"ip": "2.2.2.2", "host": "b.example"}]),
    ])
    text = hm.hosts_path.read_text(encoding="utf-8")
    xbox_i = text.index("# Xbox DNS")
    comss_i = text.index("# Comss")
    a_i = text.index("1.1.1.1 a.example")
    b_i = text.index("2.2.2.2 b.example")
    assert xbox_i < a_i < comss_i < b_i


def test_block_removed_when_state_written_without_markers_present(hm):
    """BLOCK_RE.sub на тексте без блока — no-op, не должен ничего портить."""
    before = hm._read_hosts()
    cleaned = hosts_manager.BLOCK_RE.sub("\n", before)
    assert cleaned == before


def test_is_applied_false_when_no_block(hm):
    assert hm._is_applied() is False


def test_load_state_defaults_on_missing_file(hm):
    assert hm._load_state() == {"assignments": {}, "entries": [], "enabled": True}


def test_load_state_defaults_on_corrupt_json(hm):
    hm.state_path.write_text("{not valid json", encoding="utf-8")
    assert hm._load_state() == {"assignments": {}, "entries": [], "enabled": True}


def test_save_and_load_state_roundtrip(hm):
    hm._save_state({"assignments": {"xbox": ["discord"]}, "entries": [], "enabled": False})
    assert hm._load_state()["assignments"] == {"xbox": ["discord"]}
    assert json.loads(hm.state_path.read_text(encoding="utf-8"))["enabled"] is False


def test_assignments_and_set_assignments_persist_and_sync(hm, monkeypatch):
    monkeypatch.setattr(hosts_manager, "is_admin", lambda: True)
    monkeypatch.setattr(
        hosts_manager, "resolve_domains",
        lambda domains_, doh, servers: [{"ip": "9.9.9.9", "host": d} for d in domains_],
    )
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid.upper(),
                                                         "doh": None, "servers": []})
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["example.com"], []))

    st = hm.set_assignments({"xbox": ["discord"]})
    assert st["applied"] is True
    assert st["count"] == 1
    text = hm.hosts_path.read_text(encoding="utf-8")
    assert "9.9.9.9 example.com" in text
    assert "# XBOX" in text


def test_set_assignments_drops_empty_lists(hm, monkeypatch):
    monkeypatch.setattr(hosts_manager, "is_admin", lambda: True)
    monkeypatch.setattr(
        hosts_manager, "resolve_domains",
        lambda domains_, doh, servers: [{"ip": "9.9.9.9", "host": d} for d in domains_],
    )
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid,
                                                         "doh": None, "servers": []})
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["example.com"], []))

    hm.set_assignments({"xbox": [], "comss": ["discord"]})
    # xbox с пустым списком отброшен ДО резолва — в assignments остался только comss
    assert hm.assignments() == {"comss": ["discord"]}


def test_set_enabled_false_removes_block_but_keeps_assignments(hm, monkeypatch):
    monkeypatch.setattr(hosts_manager, "is_admin", lambda: True)
    monkeypatch.setattr(
        hosts_manager, "resolve_domains",
        lambda domains_, doh, servers: [{"ip": "9.9.9.9", "host": d} for d in domains_],
    )
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid,
                                                         "doh": None, "servers": []})
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["example.com"], []))
    hm.set_assignments({"xbox": ["discord"]})
    assert hm._is_applied()

    st = hm.set_enabled(False)
    assert st["applied"] is False
    assert st["enabled"] is False
    assert hm.assignments() == {"xbox": ["discord"]}  # привязки сохранены

    st2 = hm.set_enabled(True)
    assert st2["applied"] is True  # переприменилось само


def test_sync_without_admin_raises_permission_error(hm, monkeypatch):
    monkeypatch.setattr(hosts_manager, "is_admin", lambda: False)
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid,
                                                         "doh": None, "servers": []})
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["example.com"], []))
    with pytest.raises(PermissionError):
        hm.set_assignments({"xbox": ["discord"]})


def test_sync_raises_when_nothing_resolves(hm, monkeypatch):
    monkeypatch.setattr(hosts_manager, "is_admin", lambda: True)
    monkeypatch.setattr(hosts_manager, "resolve_domains", lambda domains_, doh, servers: [])
    monkeypatch.setattr(hm, "get_provider", lambda pid: {"id": pid, "name": pid,
                                                         "doh": None, "servers": []})
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["example.com"], []))
    with pytest.raises(ValueError):
        hm.set_assignments({"xbox": ["discord"]})
