"""modules/fileutil.py — атомарная запись: читатель не видит половину файла, tmp не остаётся."""

import os

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
