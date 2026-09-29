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
