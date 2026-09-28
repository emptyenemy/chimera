"""modules/winws/manager.py — кэш version() с инвалидацией по mtime HEAD
сабмодуля (_git_head_stamp), без реального git и без побочных эффектов
WinwsManager.__init__ (не трогаем state.json/hostlist)."""

import os
import time
from types import SimpleNamespace

from modules.winws import manager


def _make_manager():
    wm = manager.WinwsManager.__new__(manager.WinwsManager)
    wm._version_cache = None
    wm._version_cached = False
    wm._version_stamp = None
    return wm


# --- _git_head_stamp: разворачивание сабмодульного .git-файла -----------------


def test_git_head_stamp_plain_git_dir(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    stamp = manager._git_head_stamp(tmp_path)
    assert stamp == (git_dir / "HEAD").stat().st_mtime_ns


def test_git_head_stamp_submodule_gitdir_pointer(tmp_path):
    real_gitdir = tmp_path / "real" / "modules" / "sub"
    real_gitdir.mkdir(parents=True)
    (real_gitdir / "HEAD").write_text("abcdef0123456789\n", encoding="utf-8")
    worktree = tmp_path / "sub-worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {real_gitdir}\n", encoding="utf-8")
    stamp = manager._git_head_stamp(worktree)
    assert stamp == (real_gitdir / "HEAD").stat().st_mtime_ns


def test_git_head_stamp_no_git_returns_none(tmp_path):
    assert manager._git_head_stamp(tmp_path) is None


def test_git_head_stamp_changes_after_checkout_simulation(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    head = git_dir / "HEAD"
    head.write_text("ref1\n", encoding="utf-8")
    stamp1 = manager._git_head_stamp(tmp_path)
    os.utime(head, (time.time() + 5, time.time() + 5))  # имитация checkout, тронувшего HEAD
    stamp2 = manager._git_head_stamp(tmp_path)
    assert stamp1 != stamp2


# --- version(): кэш и его инвалидация ------------------------------------------


def test_version_caches_result_without_recomputing(monkeypatch):
    wm = _make_manager()
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(stdout="v1.2.3\n")

    monkeypatch.setattr(manager.subprocess, "run", fake_run)
    monkeypatch.setattr(manager, "_git_head_stamp", lambda path: 111)

    assert wm.version() == "v1.2.3"
    assert wm.version() == "v1.2.3"
    assert len(calls) == 1  # второй вызов — из кэша, git не дёргали


def test_version_recomputes_after_head_stamp_changes(monkeypatch):
    wm = _make_manager()
    calls = []
    versions = iter(["v1.0.0", "v1.0.1"])

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(stdout=next(versions) + "\n")

    stamps = iter([111, 111, 222])  # версия() зовёт stamp один раз за вызов
    monkeypatch.setattr(manager.subprocess, "run", fake_run)
    monkeypatch.setattr(manager, "_git_head_stamp", lambda path: next(stamps))

    assert wm.version() == "v1.0.0"
    assert wm.version() == "v1.0.0"  # тот же stamp (111) — кэш не тронут
    assert len(calls) == 1

    assert wm.version() == "v1.0.1"  # stamp изменился (222) — пересчитали
    assert len(calls) == 2


def test_version_stamp_unresolvable_keeps_caching_forever(monkeypatch):
    """Если сабмодуль/гит не нашли (stamp всегда None) — ведём себя как раньше:
    кэшируем один раз и не дёргаем git на каждый опрос."""
    wm = _make_manager()
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(stdout="v9.9.9\n")

    monkeypatch.setattr(manager.subprocess, "run", fake_run)
    monkeypatch.setattr(manager, "_git_head_stamp", lambda path: None)

    for _ in range(3):
        assert wm.version() == "v9.9.9"
    assert len(calls) == 1
