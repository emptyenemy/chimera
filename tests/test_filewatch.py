"""modules/filewatch.py — наблюдатель за lists/*.txt.

Время и потоки не нужны: опросы вызываем руками (poll), а «файл изменили» имитируем
записью с явно сдвинутым mtime, чтобы сигнатура (mtime, size) менялась предсказуемо."""

import os
import threading

import pytest

from modules import domains, filewatch


@pytest.fixture
def env(tmp_path, monkeypatch):
    lists = tmp_path / "lists"
    lists.mkdir()
    monkeypatch.setattr(domains, "LISTS_DIR", lists)
    monkeypatch.setattr(domains, "_own", {})
    events, logs = [], []
    state = {"errors": []}

    def on_change(kind, name):
        events.append((kind, name))
        return list(state["errors"])

    w = filewatch.ListsWatcher(on_change, changes_log=tmp_path / "changes.log", log=logs.append)
    w.events, w.logs, w.state, w.dir, w.journal = events, logs, state, lists, tmp_path / "changes.log"
    return w


_tick = [1_000_000_000]


def put(env, name, text):
    """Пишет файл «снаружи» (не через domains) и сдвигает mtime, чтобы сигнатура точно поменялась."""
    p = env.dir / f"{name}.txt"
    p.write_text(text, encoding="utf-8", newline="")
    _tick[0] += 5_000_000_000
    os.utime(p, ns=(_tick[0], _tick[0]))
    return p


def settle(env, polls=2):
    for _ in range(polls):
        env.poll()


def test_existing_files_are_a_baseline_not_events(env):
    put(env, "youtube", "youtube.com\n")

    env.prime()
    settle(env, 3)

    assert env.events == []


def test_external_edit_is_applied_after_two_stable_polls(env):
    put(env, "youtube", "youtube.com\n")
    env.prime()

    put(env, "youtube", "youtube.com\nggpht.com\n")
    env.poll()
    assert env.events == []  # пока неизвестно, дописан ли файл
    env.poll()
    assert env.events == [("changed", "youtube")]
    env.poll()
    assert env.events == [("changed", "youtube")]  # повторно не применяется


def test_file_still_being_written_waits_until_it_stops_changing(env):
    put(env, "youtube", "a.com\n")
    env.prime()

    put(env, "youtube", "a.com\nb.com\n")
    env.poll()
    put(env, "youtube", "a.com\nb.com\nc.com\n")  # дописали между опросами
    env.poll()
    assert env.events == []
    env.poll()
    assert env.events == [("changed", "youtube")]


def test_new_file_is_created_event(env):
    env.prime()

    put(env, "games", "a.com\n")
    settle(env)

    assert env.events == [("created", "games")]


def test_deleted_file_is_removed_event_after_two_polls(env):
    p = put(env, "games", "a.com\n")
    env.prime()

    p.unlink()
    env.poll()
    assert env.events == []
    env.poll()
    assert env.events == [("removed", "games")]


def test_delete_and_quick_recreate_is_one_change_not_removal(env):
    p = put(env, "games", "a.com\n")
    env.prime()

    p.unlink()
    env.poll()
    put(env, "games", "b.com\n")
    settle(env)

    assert env.events == [("changed", "games")]


def test_touch_without_content_change_is_ignored(env):
    put(env, "youtube", "a.com\n")
    env.prime()

    put(env, "youtube", "a.com\n")
    settle(env, 3)

    assert env.events == []


def test_line_endings_alone_do_not_count_as_a_change(env):
    put(env, "youtube", "a.com\nb.com\n")
    env.prime()

    put(env, "youtube", "a.com\r\nb.com\r\n")
    settle(env, 3)

    assert env.events == []


def test_own_writes_through_domains_are_ignored(env):
    put(env, "youtube", "a.com\n")
    env.prime()

    domains.save_raw("youtube", "a.com\nb.com\n")
    domains.create_list("games")
    settle(env, 3)
    domains.rename_list("games", "play")
    settle(env, 3)
    domains.delete_list("play")
    settle(env, 3)

    assert env.events == []
    assert not env.journal.exists()


def test_external_edit_after_own_write_is_still_noticed(env):
    env.prime()
    domains.save_raw("youtube", "a.com\n")
    settle(env, 3)

    put(env, "youtube", "a.com\nb.com\n")
    settle(env)

    assert env.events == [("changed", "youtube")]


def test_external_delete_and_recreate_with_old_own_content_is_noticed(env):
    env.prime()
    domains.save_raw("youtube", "a.com\n")
    settle(env, 3)

    (env.dir / "youtube.txt").unlink()
    settle(env)
    put(env, "youtube", "a.com\n")
    settle(env)

    assert env.events == [("removed", "youtube"), ("created", "youtube")]


def test_not_lists_are_ignored(env):
    env.prime()

    put(env, "bad name", "a.com\n")
    (env.dir / "youtube.txt.tmp").write_text("x", encoding="utf-8")
    (env.dir / "notes.md").write_text("x", encoding="utf-8")
    settle(env, 3)

    assert env.events == []


def test_unreadable_file_is_retried(env, monkeypatch):
    put(env, "youtube", "a.com\n")
    env.prime()
    put(env, "youtube", "a.com\nb.com\n")
    real = filewatch.Path.read_bytes
    calls = []

    def flaky(self):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("занят")
        return real(self)

    monkeypatch.setattr(filewatch.Path, "read_bytes", flaky)
    settle(env, 2)
    assert env.events == []
    env.poll()
    assert env.events == [("changed", "youtube")]


def test_journal_gets_file_source_line(env):
    put(env, "youtube", "a.com\n")
    env.prime()

    put(env, "youtube", "b.com\n")
    settle(env)

    line = env.journal.read_text(encoding="utf-8").splitlines()[-1]
    parts = line.split("\t")
    assert parts[1:] == ["file", "lists edit youtube", "ok"]


def test_journal_marks_apply_errors_and_logs_them(env):
    put(env, "youtube", "a.com\n")
    env.prime()
    env.state["errors"] = [{"module": "hosts", "error": "нет прав"}]

    put(env, "youtube", "b.com\n")
    settle(env)

    assert env.journal.read_text(encoding="utf-8").splitlines()[-1].endswith("\tfile\tlists edit youtube\terror")
    assert any("hosts" in m and "нет прав" in m for m in env.logs)


def test_create_and_delete_are_journaled_with_their_verbs(env):
    p = put(env, "old", "a.com\n")
    env.prime()
    put(env, "games", "a.com\n")
    p.unlink()
    settle(env)

    text = env.journal.read_text(encoding="utf-8")
    assert "\tfile\tlists create games\tok" in text
    assert "\tfile\tlists delete old\tok" in text


def test_failing_callback_does_not_break_the_watcher(env):
    def boom(kind, name):
        raise RuntimeError("сбой")

    env._on_change = boom
    put(env, "youtube", "a.com\n")
    env.prime()
    put(env, "youtube", "b.com\n")
    settle(env)
    put(env, "youtube", "c.com\n")
    settle(env)

    assert env.journal.read_text(encoding="utf-8").count("\terror") == 2
    assert any("сбой" in m for m in env.logs)


def test_background_loop_skips_and_follows_disk_while_inactive(env):
    active = {"on": False}
    env._active = lambda: active["on"]
    put(env, "youtube", "a.com\n")
    env.prime()

    put(env, "youtube", "b.com\n")
    env._step()          # неактивен: правка не применяется, но становится «уже известной»
    env._step()
    active["on"] = True
    settle(env, 3)

    assert env.events == []


def test_start_background_primes_and_stops_with_the_event(env):
    stop = threading.Event()
    put(env, "youtube", "a.com\n")
    env.start_background(stop)
    try:
        assert env._known  # базовая линия снята синхронно, до первого опроса
    finally:
        stop.set()
    assert env._thread is not None
    env._thread.join(timeout=3)
    assert not env._thread.is_alive()
