"""ui/api.py — изменения применяются на лету: правка списка доходит до winws, прокси
и hosts; там, где без перезапуска не обойтись (игровой фильтр, блоб, продвинутые
настройки Telegram), модуль перезапускается сам, если он запущен.

Api создаём через __new__ (настоящий поднимает менеджеры и потоки), модули — заглушки."""

import pytest

from modules.winws import filters
from ui import api as api_mod


class Recorder:
    """Заглушка модуля: пишет вызовы, config — как у настоящих менеджеров."""

    def __init__(self, lists=None, running=False, **extra):
        self.config = {"lists": list(lists or [])}
        self.running = running
        self.calls = []
        self._assignments = extra.pop("assignments", {})
        self._current = extra.pop("current", None)
        self.fail = extra.pop("fail", None)
        self._ours_alive = True

    def _do(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            raise RuntimeError(self.fail)
        return {"ok": True}

    def refresh_user_lists(self): return self._do("refresh")
    def reload_lists(self): return self._do("reload")
    def resync(self): return self._do("resync")
    def assignments(self): return self._assignments
    def set_assignments(self, mapping):
        self._assignments = mapping
        return self._do("set_assignments", mapping)

    def start(self, sid): return self._do("start", sid)
    def restart(self): return self._do("restart")
    def set_lists(self, names):
        self.config["lists"] = list(names)
        return self._do("set_lists", list(names))

    def set_advanced(self, options): return {"restart_required": self.running}
    def state(self): return {"running": self.running}


@pytest.fixture
def api(monkeypatch):
    a = api_mod.Api.__new__(api_mod.Api)
    a.winws = Recorder(lists=["discord"], current="general")
    a.proxy = Recorder(lists=["discord"])
    a.hosts = Recorder(assignments={"xbox": ["discord"]})
    a.tg = Recorder()
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    monkeypatch.setattr(api_mod.domains, "save_raw", lambda name, content: {"name": name, "count": 1})
    monkeypatch.setattr(api_mod.domains, "delete_list", lambda name: None)
    return a


def names(rec):
    return [c[0] for c in rec.calls]


# --- правка содержимого списка ------------------------------------------------------

def test_lists_save_applies_to_every_consumer_of_the_list(api):
    res = api.lists_save("discord", "example.com")

    assert res["ok"] is True
    assert res["data"]["count"] == 1
    assert res["data"]["apply_errors"] == []
    assert names(api.winws) == ["refresh"]
    assert names(api.proxy) == ["reload"]
    assert names(api.hosts) == ["resync"]


def test_lists_save_skips_consumers_that_do_not_use_the_list(api):
    api.lists_save("other", "example.com")

    assert api.winws.calls == [] and api.proxy.calls == [] and api.hosts.calls == []


def test_lists_save_ignores_static_hosts_assignments(api):
    # у статического провайдера в привязке не список имён, а True
    api.hosts._assignments = {"comss": True}

    res = api.lists_save("discord", "example.com")

    assert res["ok"] is True
    assert api.hosts.calls == []


def test_lists_save_keeps_saved_data_when_a_consumer_fails(api):
    api.hosts.fail = "Нужны права администратора для записи в hosts"

    res = api.lists_save("discord", "example.com")

    assert res["ok"] is True  # файл сохранён, ошибка применения — рядом
    assert res["data"]["apply_errors"] == [
        {"module": "hosts", "error": "Нужны права администратора для записи в hosts"}]
    assert names(api.winws) == ["refresh"] and names(api.proxy) == ["reload"]


def test_lists_delete_drops_the_list_from_consumers(api):
    res = api.lists_delete("discord")

    assert res["ok"] is True
    # прокси и winws сверяют имена с существующими списками, hosts — чистим привязку
    assert names(api.proxy) == ["set_lists"] and api.proxy.calls[0][1] == ["discord"]
    assert names(api.winws) == ["set_lists"]
    assert api.hosts.calls == [("set_assignments", {})]


# --- то, что без перезапуска не применить -------------------------------------------

def test_game_filter_set_restarts_running_winws(api, monkeypatch):
    monkeypatch.setattr(filters, "set_game_mode", lambda mode: mode)
    monkeypatch.setattr(filters, "state", lambda: {"game": "all"})
    api.winws.running = True

    res = api.game_filter_set("all")

    assert res["ok"] is True and res["data"]["game"] == "all"
    assert api.winws.calls == [("start", "general")]


def test_game_filter_set_does_not_touch_stopped_winws(api, monkeypatch):
    monkeypatch.setattr(filters, "set_game_mode", lambda mode: mode)
    monkeypatch.setattr(filters, "state", lambda: {"game": "all"})

    api.game_filter_set("all")

    assert api.winws.calls == []


def test_game_filter_set_reports_restart_failure_but_keeps_setting(api, monkeypatch):
    monkeypatch.setattr(filters, "set_game_mode", lambda mode: mode)
    monkeypatch.setattr(filters, "state", lambda: {"game": "all"})
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    api.winws.running = True

    res = api.game_filter_set("all")

    assert res["ok"] is True
    assert "администратора" in res["data"]["apply_error"]
    assert api.winws.calls == []


def test_game_filter_set_does_not_restart_foreign_winws(api, monkeypatch):
    monkeypatch.setattr(filters, "set_game_mode", lambda mode: mode)
    monkeypatch.setattr(filters, "state", lambda: {"game": "all"})
    api.winws.running = True
    api.winws._ours_alive = False  # остался от прошлой сессии

    res = api.game_filter_set("all")

    assert res["ok"] is True
    assert "вручную" in res["data"]["apply_error"]
    assert api.winws.calls == []


def test_fake_set_restarts_running_winws(api, monkeypatch):
    monkeypatch.setattr(filters, "set_fake", lambda slot, name: {"slot": slot})
    api.winws.running = True

    res = api.fake_set("discord", "quic_1")

    assert res["data"]["slot"] == "discord"
    assert api.winws.calls == [("start", "general")]


def test_winws_set_lists_needs_no_admin_because_no_restart(api, monkeypatch):
    monkeypatch.setattr(api_mod, "is_admin", lambda: False)
    api.winws.running = True

    res = api.winws_set_lists(["discord"])

    assert res["ok"] is True


def test_tg_set_advanced_restarts_running_proxy_itself(api):
    api.tg.running = True

    res = api.tg_set_advanced({"fake_tls_domain": "example.com"})

    assert res["ok"] is True
    assert "restart_required" not in res["data"]
    assert api.tg.calls == [("restart",)]


def test_tg_set_advanced_does_not_start_stopped_proxy(api):
    res = api.tg_set_advanced({"fake_tls_domain": "example.com"})

    assert res["ok"] is True
    assert api.tg.calls == []


# --- явное применение (chimera lists apply) ------------------------------------------

def test_lists_apply_one_list_reports_modules_and_errors(api, monkeypatch):
    monkeypatch.setattr(api_mod.domains, "read_raw", lambda name: "x")
    api.hosts.fail = "нет прав"

    res = api.lists_apply("discord")

    assert res["ok"] is True
    assert res["data"]["applied"] == ["discord"]
    assert res["data"]["modules"] == ["winws", "proxy", "hosts"]
    assert res["data"]["apply_errors"] == [{"module": "hosts", "error": "нет прав"}]
    assert names(api.winws) == ["refresh"] and names(api.proxy) == ["reload"]


def test_lists_apply_without_name_covers_every_list_once(api, monkeypatch):
    monkeypatch.setattr(api_mod.domains, "available_lists", lambda: ["discord", "youtube"])

    res = api.lists_apply()

    assert res["data"]["applied"] == ["discord", "youtube"]
    assert names(api.winws) == ["refresh"] and names(api.hosts) == ["resync"]


def test_lists_apply_unknown_list_is_an_error(api, monkeypatch):
    def missing(name):
        raise FileNotFoundError(f"Список {name!r} не найден")

    monkeypatch.setattr(api_mod.domains, "read_raw", missing)

    res = api.lists_apply("nope")

    assert res["ok"] is False and "nope" in res["error"]
    assert api.winws.calls == []


# --- правка файлов напрямую (modules/filewatch.py) -----------------------------------

def test_file_change_from_watcher_is_applied_like_lists_save(api):
    api.hub = type("Hub", (), {"poked": [], "poke": lambda self, *k: self.poked.append(k)})()

    errors = api._lists_file_changed("changed", "discord")

    assert errors == []
    assert names(api.winws) == ["refresh"] and names(api.proxy) == ["reload"] and names(api.hosts) == ["resync"]
    assert api.hub.poked  # счётчики доменов на вкладках обновятся сразу


def test_shutdown_stops_watcher_before_modules(api, monkeypatch):
    import threading

    order = []
    monkeypatch.setattr(api_mod.control, "stop_current", lambda: None)
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    api.hub = type("Hub", (), {"stop": lambda self: None})()
    api._bg_stop = threading.Event()
    api.lists_watcher = type("W", (), {"stop": lambda self: order.append("watcher")})()
    api.hosts.stop_background = lambda: order.append("hosts")
    api.winws.stop = lambda: order.append("winws")
    api.proxy.stop = lambda: order.append("proxy")

    api.shutdown()

    assert order[0] == "watcher" and "winws" in order


def test_file_removal_from_watcher_drops_list_from_consumers(api):
    api._lists_file_changed("removed", "discord")

    assert names(api.proxy) == ["set_lists"] and names(api.winws) == ["set_lists"]
    assert api.hosts.calls == [("set_assignments", {})]


def test_watch_lists_starts_watcher_only_for_the_process_owner(api, monkeypatch):
    import threading

    made = {}

    class FakeWatcher:
        def __init__(self, on_change, active, **kw):
            made["active"] = active

        def start_background(self, stop):
            made["stop"] = stop

    monkeypatch.setattr(api_mod.filewatch, "ListsWatcher", FakeWatcher)
    api._bg_stop = threading.Event()

    api._watch_lists()

    assert made["stop"] is api._bg_stop
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    assert made["active"]() is False  # при работающей службе окно не следит
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    assert made["active"]() is True
