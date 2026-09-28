"""Логика трея: подписи состояния и команды модулей (без Qt)."""

import pytest

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


def test_tooltip():
    assert tm.tooltip({}) == "Chimera"
    assert tm.tooltip({"proxy": {"running": True}}) == "Chimera — защита активна · 1 из 4"


def test_winws_start_uses_current_then_last_then_first():
    strategies = [{"id": "a"}, {"id": "b"}]
    assert tm.toggle_command("winws", {"current": "b", "last_strategy": "a", "strategies": strategies}, True) \
        == ("winws_start", ["b"])
    assert tm.toggle_command("winws", {"last_strategy": "b", "strategies": strategies}, True) == ("winws_start", ["b"])
    assert tm.toggle_command("winws", {"strategies": strategies}, True) == ("winws_start", ["a"])


def test_winws_start_without_strategies_explains():
    with pytest.raises(ValueError, match="Нет стратегий"):
        tm.toggle_command("winws", {"strategies": []}, True)


def test_other_commands():
    assert tm.toggle_command("winws", {}, False) == ("winws_stop", [])
    assert tm.toggle_command("proxy", {}, True) == ("proxy_start", [])
    assert tm.toggle_command("tg", {}, False) == ("tg_stop", [])
    assert tm.toggle_command("hosts", {}, False) == ("hosts_set_enabled", [False])
