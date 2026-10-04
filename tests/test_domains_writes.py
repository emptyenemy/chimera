"""Failed list operations must not hide later external changes from the watcher."""

from pathlib import Path

import pytest

from modules import domains, filewatch


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(domains, "LISTS_DIR", tmp_path)
    monkeypatch.setattr(domains, "_own", {})
    return tmp_path


def fail(*args, **kwargs):
    raise OSError("disk unavailable")


@pytest.mark.parametrize("operation", ["save", "create", "delete", "rename"])
def test_failed_operation_leaves_no_own_marker(isolated, monkeypatch, operation):
    if operation != "create":
        (isolated / "sample.txt").write_text("example.com\n", encoding="utf-8")
    monkeypatch.setattr(domains, "atomic_write_text", fail)
    monkeypatch.setattr(Path, "unlink", fail)
    monkeypatch.setattr(Path, "rename", fail)
    monkeypatch.setattr(domains, "replace_file", fail)
    actions = {
        "save": lambda: domains.save_raw("sample", "new.example\n"),
        "create": lambda: domains.create_list("sample"),
        "delete": lambda: domains.delete_list("sample"),
        "rename": lambda: domains.rename_list("sample", "next"),
    }
    with pytest.raises(OSError, match="disk unavailable"):
        actions[operation]()
    assert domains.own_written("sample") == (False, None)
    assert domains.own_written("next") == (False, None)


def test_failed_write_restores_previous_successful_marker(isolated, monkeypatch):
    domains.save_raw("sample", "original.example\n")
    marker = domains.own_written("sample")
    monkeypatch.setattr(domains, "atomic_write_text", fail)
    with pytest.raises(OSError):
        domains.save_raw("sample", "failed.example\n")
    assert domains.own_written("sample") == marker
    assert domains.read_raw("sample") == "original.example\n"


def test_failed_write_does_not_remove_a_newer_successful_marker(isolated, monkeypatch):
    marker = ("newer", domains._clock())

    def fail_after_newer_write(*args):
        domains._own["sample"] = marker
        fail()

    monkeypatch.setattr(domains, "atomic_write_text", fail_after_newer_write)
    with pytest.raises(OSError):
        domains.save_raw("sample", "failed.example\n")
    assert domains.own_written("sample") == (True, "newer")


def test_available_lists_ignore_directories_and_unusable_names(isolated):
    (isolated / "directory.txt").mkdir()
    (isolated / "invalid name.txt").write_text("example.com", encoding="utf-8")
    (isolated / "valid.txt").write_text("example.com", encoding="utf-8")
    assert domains.list_info() == [{"name": "valid", "count": 1}]


def test_watcher_ignores_directories_named_like_lists(isolated):
    (isolated / "directory.txt").mkdir()
    (isolated / "valid.txt").write_text("example.com", encoding="utf-8")
    watcher = filewatch.ListsWatcher(lambda *args: [], directory=isolated)
    assert set(watcher._scan()) == {"valid"}
