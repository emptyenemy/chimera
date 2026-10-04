"""Самолечение в фоне: чинит только то, что уже чинили в этой сети, и только после двух
неудачных проверок подряд."""

import threading

import pytest

from modules.autotune import memory
from modules.autotune.manager import AutotuneManager
from modules.autotune.watch import AutotuneWatch
from tests.autotune_net import FakeOps, blocked_unless


@pytest.fixture
def env(tmp_path):
    ops = FakeOps({"youtube": ["youtube.com"], "discord": ["discord.com"]}, {
        "youtube.com": blocked_unless(lambda s: s["strategy"] == "alt"),
        "discord.com": blocked_unless(lambda s: True)}, hosts=(), dns_plain=(), dns_unblock=())
    mem = tmp_path / "memory.json"
    mgr = AutotuneManager(ops, tmp_path / "autotune.json", threading.RLock(), memory_path=mem, worker=lambda fn: fn())
    flags = {"enabled": True, "can_run": True}
    watch = AutotuneWatch(mgr, enabled=lambda: flags["enabled"], can_run=lambda: flags["can_run"], memory_path=mem)
    return ops, mgr, watch, mem, flags


def test_nothing_is_watched_until_auto_setup_fixed_something_here(env):
    ops, _, watch, _, _ = env
    assert watch.run_once() is None and ops.calls == []


def test_one_failed_check_is_not_enough_two_in_a_row_start_a_fix(env):
    ops, mgr, watch, mem, _ = env
    memory.remember("net", {"youtube": {"kind": "strategy", "id": "alt"}}, mem)
    assert watch.run_once()["due"] == [] and ops.calls == []      # сайт мог моргнуть
    result = watch.run_once()
    assert result["due"] == ["youtube"] and ops.state["strategy"] == "alt"
    session = mgr.state()["active"]
    assert session["phase"] == "done" and session["trigger"] == "watch" and session["services"] == ["youtube"]


def test_a_service_that_recovers_resets_its_count(env):
    ops, _, watch, mem, _ = env
    memory.remember("net", {"youtube": {"kind": "strategy", "id": "alt"}}, mem)
    watch.run_once()
    ops.state["strategy"] = "alt"   # сам ожил
    assert watch.run_once()["due"] == [] and watch.streak == {}
    ops.state["strategy"] = None
    assert watch.run_once()["due"] == []


def test_without_internet_nothing_is_counted_and_the_count_starts_over(env):
    ops, _, watch, mem, _ = env
    memory.remember("net", {"youtube": {"kind": "strategy", "id": "alt"}}, mem)
    watch.run_once()                                   # одна неудача при живом интернете
    ops.canary = {"ya.ru": lambda s: ("blocked", None), "example.com": lambda s: ("blocked", None)}
    for _ in range(3):
        assert watch.run_once()["offline"] is True
    ops.canary = {}
    assert watch.run_once()["due"] == []               # счёт начался заново: одна неудача — не повод
    assert ops.calls == []


@pytest.mark.parametrize("flag", ["enabled", "can_run"])
def test_switched_off_or_busy_does_nothing(env, flag):
    ops, _, watch, mem, flags = env
    memory.remember("net", {"youtube": {"kind": "strategy", "id": "alt"}}, mem)
    flags[flag] = False
    assert watch.run_once() is None and watch.run_once() is None and ops.calls == []


def test_running_session_is_not_interrupted(env, tmp_path):
    ops, _, _, mem, _ = env
    memory.remember("net", {"youtube": {"kind": "strategy", "id": "alt"}}, mem)
    pending = []
    mgr = AutotuneManager(ops, tmp_path / "other.json", threading.RLock(), memory_path=mem, worker=pending.append)
    mgr.start(["discord"])
    watch = AutotuneWatch(mgr, enabled=lambda: True, memory_path=mem)
    assert watch.run_once() is None


def test_missing_rights_are_reported_not_raised(env):
    ops, _, watch, mem, _ = env
    memory.remember("net", {"youtube": {"kind": "strategy", "id": "alt"}}, mem)
    ops.admin = False
    watch.run_once()
    result = watch.run_once()
    assert result["error"] == "err.autotune.admin" and ops.state["strategy"] is None
