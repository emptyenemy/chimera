"""Сессия автонастройки: результат, откат, отмена, авария и «Выключить всё»."""

import json
import threading

import pytest

from modules.autotune import manager as manager_mod
from modules.autotune.engine import Cancelled
from modules.autotune.manager import AutotuneManager
from modules.errors import ChimeraError
from tests.autotune_net import FakeOps, blocked_unless

YT = {"youtube": ["youtube.com"], "discord": ["discord.com"]}


def network():
    return FakeOps(YT, {"youtube.com": blocked_unless(lambda s: s["strategy"] == "alt"),
                        "discord.com": blocked_unless(lambda s: True)}, hosts=(), dns_plain=(), dns_unblock=())


@pytest.fixture
def make(tmp_path):
    def build(ops=None, worker=None):
        ops = ops or network()
        mgr = AutotuneManager(ops, tmp_path / "autotune.json", threading.RLock(), memory_path=tmp_path / "memory.json",
                              worker=worker or (lambda fn: fn()))
        return mgr, ops
    return build


def test_finished_session_keeps_the_result_and_offers_revert(make, tmp_path):
    mgr, ops = make()
    state = mgr.start()
    active = state["active"]
    assert active["phase"] == "done" and "before" not in active
    assert ops.state["strategy"] == "alt" and ("snapshot",) in ops.calls
    fixes = {r["name"]: r["fix"] for r in active["report"]["services"]}
    assert fixes == {"youtube": {"kind": "strategy", "id": "alt"}, "discord": None}
    assert json.loads((tmp_path / "autotune.json").read_text(encoding="utf-8"))["before"]["strategy"] is None


def test_keep_forgets_the_original_state(make, tmp_path):
    mgr, ops = make()
    mgr.start()
    state = mgr.keep()
    assert state["active"] is None and state["last"]["phase"] == "kept"
    assert not (tmp_path / "autotune.json").exists() and ops.restored == []


def test_revert_returns_everything_as_it_was(make, tmp_path):
    mgr, ops = make()
    ops.state.update(strategy="general", winws_lists=["discord"])
    mgr.start()
    state = mgr.revert()
    assert ops.state["strategy"] == "general" and ops.state["winws_lists"] == ["discord"]
    assert state["last"]["phase"] == "reverted" and not (tmp_path / "autotune.json").exists()


def test_cancel_during_search_rolls_back(make):
    holder = {}
    ops = network()
    ops.hooks["apply_strategy"] = lambda sid: holder["mgr"].cancel()
    mgr, _ = make(ops)
    holder["mgr"] = mgr
    state = mgr.start()
    assert state["last"]["phase"] == "cancelled" and ops.state["strategy"] is None
    assert ops.applied("apply_strategy") == ["general"]   # после отмены ничего больше не применялось


def test_engine_failure_rolls_back_and_reports(make):
    ops = network()
    ops.targets = lambda name: (_ for _ in ()).throw(RuntimeError("boom"))
    mgr, _ = make(ops)
    state = mgr.start()
    assert state["last"]["phase"] == "failed" and state["last"]["error"] == "boom" and len(ops.restored) == 1


def test_running_session_blocks_a_second_one_and_changes(make):
    started = []
    mgr, ops = make(worker=started.append)   # поток не запускается: подбор «идёт»
    mgr.start()
    assert mgr.busy() and mgr.blocks_changes()
    with pytest.raises(ChimeraError) as e:
        mgr.start()
    assert e.value.code == "err.autotune.busy"


def test_interrupted_session_is_restored_on_next_start(make, tmp_path):
    mgr, ops = make(worker=lambda fn: None)
    ops.state["strategy"] = "general"
    mgr.start()
    ops.state["strategy"] = "alt2"             # программа упала посреди перебора
    again = AutotuneManager(ops, tmp_path / "autotune.json", threading.RLock(), memory_path=tmp_path / "memory.json")
    assert again.state()["active"]["phase"] == "interrupted" and again.blocks_changes()
    again.recover()
    assert ops.state["strategy"] == "general" and again.state()["last"]["phase"] == "interrupted"
    assert not (tmp_path / "autotune.json").exists()


def test_damaged_record_blocks_changes_until_reverted(make, tmp_path):
    (tmp_path / "autotune.json").write_text("{broken", encoding="utf-8")
    mgr, _ = make()
    assert mgr.state()["active"]["phase"] == "invalid" and mgr.blocks_changes()
    with pytest.raises(ChimeraError):
        mgr.start()


def test_panic_closes_the_session_without_turning_modules_back_on(make):
    mgr, ops = make(worker=lambda fn: None)
    mgr.start()
    mgr.abandon()
    assert mgr.state()["last"]["reason"] == "panic" and ops.restored == [] and not mgr.blocks_changes()


def test_mutations_after_cancel_never_reach_the_system():
    ops = network()
    cancel = threading.Event()
    guarded = manager_mod._GuardedOps(ops, threading.RLock(), cancel)
    guarded.apply_strategy("alt")
    cancel.set()
    with pytest.raises(Cancelled):
        guarded.apply_strategy("alt2")
    assert guarded.check("youtube.com")["status"] == "ok"   # проверки после отмены не запрещены
    assert ops.applied("apply_strategy") == ["alt"]


def test_working_variant_is_remembered_for_the_network(make):
    mgr, ops = make()
    mgr.start()
    mgr.keep()
    ops.state["strategy"] = None
    ops.calls.clear()
    mgr.start()
    assert ops.applied("apply_strategy")[0] == "alt"   # запомненная стратегия — первой


def test_unknown_service_and_mode_are_rejected(make):
    mgr, _ = make()
    with pytest.raises(ChimeraError) as e:
        mgr.start(["nope"])
    assert e.value.code == "err.autotune.unknown_service"
    with pytest.raises(ChimeraError):
        mgr.start(mode="turbo")


def test_without_admin_rights_nothing_starts(make, tmp_path):
    ops = network()
    ops.admin = False
    mgr, _ = make(ops)
    with pytest.raises(ChimeraError) as e:
        mgr.start()
    assert e.value.code == "err.autotune.admin" and not (tmp_path / "autotune.json").exists() and ops.calls == []


def test_progress_is_visible_in_the_state(make):
    seen = []
    mgr, ops = make()
    ops.hooks["apply_strategy"] = lambda sid: seen.append(mgr.state()["active"]["current"])
    mgr.start()
    assert seen[0] == {"step": "strategy", "candidate": "general", "index": 0, "total": 3}
    log = mgr.state()["active"]["log"]
    assert [e["candidate"] for e in log if e["type"] == "result"][:2] == ["general", "alt"]


def test_diagnose_changes_nothing(make):
    mgr, ops = make()
    result = mgr.diagnose(["youtube"])
    assert result["services"][0]["reasons"] == ["dpi"] and ops.calls == [] and mgr.state()["active"] is None
