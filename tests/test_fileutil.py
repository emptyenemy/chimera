"""modules/fileutil.py — атомарная запись: читатель не видит половину файла, tmp не остаётся."""

import os
import sys

import pytest

from modules import appconfig, domains, fileutil


def test_atomic_write_creates_and_replaces(tmp_path):
    target = tmp_path / "a.txt"
    fileutil.atomic_write_text(target, "one\n")
    fileutil.atomic_write_text(target, "two\n")

    assert target.read_text(encoding="utf-8") == "two\n"
    assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]


def test_atomic_write_goes_through_tmp_and_replace(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"
    seen = []
    real = os.replace
    monkeypatch.setattr(fileutil.os, "replace", lambda src, dst: (seen.append((str(src), str(dst))), real(src, dst)))

    fileutil.atomic_write_text(target, "x\n")

    assert len(seen) == 1 and seen[0][1] == str(target)
    assert seen[0][0].startswith(str(target)) and seen[0][0].endswith(".tmp")


def test_atomic_write_uses_unique_tmp_and_cleans_it_on_write_error(tmp_path):
    target = tmp_path / "a.txt"
    (tmp_path / "a.txt.tmp").write_text("чужой", encoding="utf-8")  # фиксированное имя не занять

    fileutil.atomic_write_text(target, "x\n")
    assert (tmp_path / "a.txt.tmp").read_text(encoding="utf-8") == "чужой"

    with pytest.raises(UnicodeEncodeError):
        fileutil.atomic_write_text(target, "\ud800", encoding="utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt", "a.txt.tmp"]


def test_atomic_write_retries_when_target_is_briefly_locked(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"
    real = os.replace
    attempts = []

    def flaky(src, dst):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("занят")
        real(src, dst)

    monkeypatch.setattr(fileutil.os, "replace", flaky)
    monkeypatch.setattr(fileutil.time, "sleep", lambda s: None)

    fileutil.atomic_write_text(target, "x\n")

    assert len(attempts) == 3 and target.read_text(encoding="utf-8") == "x\n"


def test_atomic_write_gives_up_and_cleans_tmp(tmp_path, monkeypatch):
    target = tmp_path / "a.txt"
    monkeypatch.setattr(fileutil.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("занят")))
    monkeypatch.setattr(fileutil.time, "sleep", lambda s: None)

    with pytest.raises(PermissionError):
        fileutil.atomic_write_text(target, "x\n")

    assert list(tmp_path.iterdir()) == []


def test_save_raw_and_create_list_leave_no_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(domains, "LISTS_DIR", tmp_path)

    domains.create_list("svc")
    domains.save_raw("svc", "a.com\r\nb.com")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["svc.txt"]
    assert (tmp_path / "svc.txt").read_text(encoding="utf-8") == "a.com\nb.com\n"


def test_appconfig_write_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")

    appconfig.set_value("update_channel", "beta")

    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]
    assert appconfig.load()["update_channel"] == "beta"


def test_atomic_binary_write_preserves_exact_bytes_and_previous_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "blob.bin"
    before = bytes(range(256)) + b"\r\n\n\x00"
    fileutil.atomic_write_bytes(target, before)
    assert target.read_bytes() == before
    real_replace = fileutil.os.replace

    def fail(source, destination):
        assert target.read_bytes() == before
        raise PermissionError("Simulated permanent lock")

    monkeypatch.setattr(fileutil.os, "replace", fail)
    monkeypatch.setattr(fileutil.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        fileutil.atomic_write_bytes(target, b"new")
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]
    monkeypatch.setattr(fileutil.os, "replace", real_replace)
    fileutil.atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"


def test_unknown_encoding_closes_descriptor_and_removes_staging_file(tmp_path, monkeypatch):
    target = tmp_path / "text.txt"
    target.write_bytes(b"previous")
    real_mkstemp = fileutil.tempfile.mkstemp
    descriptors = []

    def mkstemp(*args, **kwargs):
        descriptor, path = real_mkstemp(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor, path

    monkeypatch.setattr(fileutil.tempfile, "mkstemp", mkstemp)
    with pytest.raises(LookupError):
        fileutil.atomic_write_text(target, "new", encoding="not-an-encoding")
    assert target.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [target]
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def _hold(path, seconds):
    """Держит файл открытым без права удаления — так его открывает Python в соседнем процессе:
    os.replace на него падает, пока держат."""
    import ctypes
    import threading
    from ctypes import wintypes as w
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = w.HANDLE
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    handle = k.CreateFileW(str(path), 0x80000000, 1 | 2, None, 3, 0, None)
    timer = threading.Timer(seconds, lambda: k.CloseHandle(handle))
    timer.start()
    return timer


@pytest.mark.skipif(sys.platform != "win32", reason="блокировка файла — Windows")
def test_a_target_held_by_another_reader_is_replaced_once_released(tmp_path):
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    timer = _hold(target, 0.3)
    fileutil.atomic_write_text(target, "new")
    timer.join()
    assert target.read_text(encoding="utf-8") == "new"


@pytest.mark.skipif(sys.platform != "win32", reason="блокировка файла — Windows")
def test_a_target_held_too_long_says_which_file_and_stays_intact(tmp_path, monkeypatch):
    from modules.errors import ChimeraPermissionError
    monkeypatch.setattr(fileutil.time, "sleep", lambda s: None)
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    timer = _hold(target, 0.5)
    with pytest.raises(ChimeraPermissionError) as error:
        fileutil.atomic_write_text(target, "new")
    timer.join()
    assert error.value.code == "err.file.busy" and error.value.params == {"name": "state.json"}
    assert target.read_text(encoding="utf-8") == "old" and sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_prepare_sees_the_new_file_before_it_takes_the_place_of_the_old(tmp_path):
    target = tmp_path / "secret.json"
    target.write_text("old", encoding="utf-8")
    seen = []
    fileutil.atomic_write_text(target, "new", prepare=lambda tmp: seen.append((tmp.read_text(encoding="utf-8"),
                                                                                target.read_text(encoding="utf-8"))))
    assert seen == [("new", "old")] and target.read_text(encoding="utf-8") == "new"


def test_replace_file_waits_until_the_target_is_free(tmp_path, monkeypatch):
    monkeypatch.setattr(fileutil.time, "sleep", lambda s: None)
    source, target = tmp_path / "a.txt", tmp_path / "b.txt"
    source.write_text("new", encoding="utf-8")
    real, attempts = fileutil.os.replace, []

    def flaky(src, dst):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(13, "Permission denied")
        return real(src, dst)
    monkeypatch.setattr(fileutil.os, "replace", flaky)
    fileutil.replace_file(source, target)
    assert target.read_text(encoding="utf-8") == "new" and len(attempts) == 3

