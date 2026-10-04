"""Логика трея: подписи состояния и команды модулей (без Qt)."""

import pytest

from modules import i18n
from modules.errors import ChimeraError
from ui import tray_model as tm


def test_summary_all_off():
    assert tm.summary({}) == (False, 0, "Всё выключено")


def test_summary_guard_from_traffic_modules():
    states = {"winws": {"running": True}, "hosts": {"applied": True}, "proxy": {"running": False}}
    assert tm.summary(states) == (True, 2, "Защита активна · 2 из 4")


def test_summary_tg_alone_is_not_guard():
    # tg-прокси работает только для Telegram — «защитой» не считается, как и в сайдбаре
    assert tm.summary({"tg": {"running": True}}) == (False, 1, "1 из 4 включено")


def test_hosts_on_means_applied_not_enabled():
    assert tm.is_on("hosts", {"enabled": True, "applied": False}) is False
    assert tm.is_on("hosts", {"applied": True}) is True



def test_winws_start_uses_current_then_last_then_first():
    strategies = [{"id": "a"}, {"id": "b"}]
    assert tm.toggle_command("winws", {"current": "b", "last_strategy": "a", "strategies": strategies}, True) \
        == ("winws_start", ["b"])
    assert tm.toggle_command("winws", {"last_strategy": "b", "strategies": strategies}, True) == ("winws_start", ["b"])
    assert tm.toggle_command("winws", {"strategies": strategies}, True) == ("winws_start", ["a"])


def test_winws_start_without_strategies_explains():
    with pytest.raises(ChimeraError, match="Нет стратегий"):
        tm.toggle_command("winws", {"strategies": []}, True)


def test_other_commands():
    assert tm.toggle_command("winws", {}, False) == ("winws_stop", [])
    assert tm.toggle_command("proxy", {}, True) == ("proxy_start", [])
    assert tm.toggle_command("tg", {}, False) == ("tg_stop", [])
    assert tm.toggle_command("hosts", {}, False) == ("hosts_set_enabled", [False])


def test_panic_command_and_label():
    assert tm.PANIC_COMMAND == ("panic_all", [])
    assert tm.panic_label() == "Выключить всё"


def test_panic_summary_is_silent_when_everything_stopped():
    assert tm.panic_summary({"steps": [{"step": "winws", "ok": True}], "failed": 0}) is None
    assert tm.panic_summary(None) is None


def test_panic_summary_lists_failed_steps():
    data = {"steps": [{"step": "winws", "ok": True},
                      {"step": "hosts", "ok": False, "error": "Нужны права администратора"},
                      {"step": "dns", "ok": False, "error": "адаптер 3: нет доступа"}],
            "failed": 2}
    text = tm.panic_summary(data)
    assert "hosts: Нужны права администратора" in text
    assert "dns: адаптер 3: нет доступа" in text
    assert "winws" not in text


# --- языки ----------------------------------------------------------------------------------

def test_tray_texts_follow_the_language():
    with i18n.using("en"):
        assert tm.panic_label() == "Turn everything off"
        assert tm.module_label("winws") == "DPI bypass"
        assert tm.summary({}) == (False, 0, "Everything is off")
        assert tm.summary({"winws": {"running": True}})[2] == "Protection on · 1 of 4"
        assert tm.summary({"tg": {"running": True}})[2] == "1 of 4 on"


def test_every_module_has_a_label_in_both_languages():
    for lang in ("ru", "en"):
        with i18n.using(lang):
            for key, _ in tm.MODULES:
                assert tm.module_label(key) and not tm.module_label(key).startswith("tray.")


def test_no_strategies_error_has_a_code_and_a_text_per_language():
    with pytest.raises(ChimeraError) as e:
        tm.toggle_command("winws", {"strategies": []}, True)
    assert e.value.code == "err.strategies.none"
    assert e.value.message("en") == "No strategies available. Pick one on the Strategies tab."


def test_panic_summary_uses_codes_when_present_and_text_otherwise():
    data = {"steps": [{"step": "hosts", "ok": False, "error": "Нужны права администратора для записи в hosts",
                       "code": "err.admin.hosts", "params": {}},
                      {"step": "dns", "ok": False, "error": "чужой текст"}]}
    assert tm.panic_summary(data).splitlines() == ["hosts: Нужны права администратора для записи в hosts",
                                                   "dns: чужой текст"]
    with i18n.using("en"):
        assert tm.panic_summary(data).splitlines() == [
            "hosts: Administrator rights are required to edit the hosts file.", "dns: чужой текст"]


# --- итог самолечения в фоне ----------------------------------------------------------------

def _session(sid, phase="done", trigger="watch", rows=()):
    return {"active": {"id": sid, "phase": phase, "trigger": trigger, "report": {"services": list(rows)}}, "last": None}


FIXED = {"name": "youtube", "fix": {"kind": "strategy", "id": "alt"}, "after": {"ok": True}}
BROKEN = {"name": "discord", "fix": None, "after": {"ok": False}}


def test_a_background_fix_is_announced_once():
    news = tm.AutotuneNews()
    assert news.update(None) is None
    assert news.update(_session("a", rows=[FIXED])) == ("Chimera починила сама", "youtube снова открывается: стратегия alt")
    assert news.update(_session("a", rows=[FIXED])) is None
    # «Готово» переносит ту же сессию в last — повтора нет
    assert news.update({"active": None, "last": {**_session("a")["active"], "phase": "kept"}}) is None


def test_results_from_before_the_tray_started_are_not_announced():
    news = tm.AutotuneNews()
    assert news.update(_session("old", rows=[FIXED])) is None
    assert news.update(_session("old", rows=[FIXED])) is None


def test_a_fix_running_when_the_tray_starts_is_announced_when_it_ends():
    news = tm.AutotuneNews()
    assert news.update(_session("b", phase="running")) is None
    assert news.update(_session("b", rows=[FIXED, BROKEN]))[0] == "Chimera починила не всё"


def test_only_background_results_are_announced():
    news = tm.AutotuneNews()
    news.update(None)
    assert news.update(_session("c", trigger="user", rows=[FIXED])) is None


def test_a_failed_background_fix_says_so():
    news = tm.AutotuneNews()
    news.update(None)
    with i18n.using("en"):
        assert news.update(_session("d", rows=[BROKEN])) == (
            "Self-healing did not help", "discord does not open; details on the Auto-setup page")


def test_the_webview_tray_reads_news_from_the_hub_without_a_window():
    from ui.tray_win32 import Tray
    states = {}
    tray = Tray.__new__(Tray)   # без потока и значка: только чтение итога
    tray.api = type("Api", (), {"hub": type("Hub", (), {"snapshot": staticmethod(lambda: states)})()})()
    tray.autotune_news = tm.AutotuneNews()
    assert tray.news() is None
    states["autotune"] = _session("w", rows=[FIXED])
    assert tray.news()[0] == "Chimera починила сама"
