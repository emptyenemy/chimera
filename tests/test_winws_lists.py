"""modules/winws/manager.py — списки доменов применяются без перезапуска стратегии.

zapret2 сам перечитывает hostlist и ipset при изменении файла, поэтому смена
списков — это перегенерация list-general-user.txt и ipset-user.txt, а не рестарт.
Пути рантайм-файлов лежат в strategies/hostlists (не в data/), так что их надо
уводить во временную папку, иначе тесты перепишут настоящие."""

import pytest

from modules.winws import manager


@pytest.fixture
def wm(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "USER_HOSTLIST_PATH", tmp_path / "list-general-user.txt")
    monkeypatch.setattr(manager, "USER_IPSET_PATH", tmp_path / "ipset-user.txt")
    monkeypatch.setattr(manager, "STATE_PATH", tmp_path / "winws.json")
    monkeypatch.setattr(manager.WinwsManager, "running", property(lambda self: True))
    monkeypatch.setattr(manager.WinwsManager, "state", lambda self: {})
    monkeypatch.setattr("modules.domains.list_info", lambda: [{"name": "somelist"}])
    monkeypatch.setattr("modules.domains.split_lists",
                        lambda names: (["example.com", "foo.example"], ["10.0.0.0/24"]))
    m = manager.WinwsManager.__new__(manager.WinwsManager)
    m.config = {"lists": [], "last_strategy": "general"}
    m._current = "general"
    return m


def test_set_lists_regenerates_files_without_restarting_running_strategy(wm, monkeypatch):
    monkeypatch.setattr(wm, "start", lambda sid: pytest.fail("рестарт не нужен — winws2 сам перечитает файлы"))

    wm.set_lists(["somelist"])

    assert wm.config["lists"] == ["somelist"]
    assert manager.USER_HOSTLIST_PATH.read_text(encoding="utf-8") == "example.com\nfoo.example\n"
    assert manager.USER_IPSET_PATH.read_text(encoding="utf-8") == "10.0.0.0/24\n"


def test_select_strategy_remembers_it_without_starting_or_restarting(wm, tmp_path, monkeypatch):
    (tmp_path / "alt2.txt").write_text("--filter-tcp=443\n", encoding="utf-8")
    monkeypatch.setattr(manager, "STRATEGIES_DIR", tmp_path)
    monkeypatch.setattr(wm, "start", lambda sid: pytest.fail("выбор стратегии её не запускает"))

    wm.select_strategy("alt2")

    assert wm.config["last_strategy"] == "alt2"
    assert '"alt2"' in manager.STATE_PATH.read_text(encoding="utf-8")


def test_select_unknown_strategy_is_an_error(wm, tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "STRATEGIES_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        wm.select_strategy("no-such")
    assert wm.config["last_strategy"] == "general"


def test_refresh_user_lists_rewrites_files_from_current_config(wm):
    wm.config["lists"] = ["somelist"]

    wm.refresh_user_lists()

    assert manager.USER_HOSTLIST_PATH.read_text(encoding="utf-8") == "example.com\nfoo.example\n"


def test_refresh_user_lists_uses_placeholder_when_no_subnets(wm, monkeypatch):
    monkeypatch.setattr("modules.domains.split_lists", lambda names: (["example.com"], []))
    wm.config["lists"] = ["somelist"]

    wm.refresh_user_lists()

    # пустой ipset zapret трактует как «без ограничений по IP» — нужна заглушка
    assert manager.USER_IPSET_PATH.read_text(encoding="utf-8") == manager.IPSET_PLACEHOLDER + "\n"
