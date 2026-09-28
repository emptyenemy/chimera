"""Подготовка бинарников для сборки (tools/fetch_bins.py) — без сети."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("fetch_bins", ROOT / "tools" / "fetch_bins.py")
fetch_bins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_bins)


def test_copy_winws_takes_only_winws_folder(tmp_path):
    src = tmp_path / "bundle"
    (src / "zapret-winws" / "lua").mkdir(parents=True)
    (src / "zapret-winws" / "winws2.exe").write_bytes(b"exe")
    (src / "zapret-winws" / "lua" / "a.lua").write_text("x")
    (src / "cygwin").mkdir()
    (src / "cygwin" / "big.dll").write_bytes(b"0" * 10)
    dest = tmp_path / "out" / "zapret-win-bundle"

    fetch_bins.copy_winws(src, dest)

    assert (dest / "zapret-winws" / "winws2.exe").read_bytes() == b"exe"
    assert (dest / "zapret-winws" / "lua" / "a.lua").exists()
    assert not (dest / "cygwin").exists()


def test_copy_winws_replaces_previous_copy(tmp_path):
    src = tmp_path / "bundle"
    (src / "zapret-winws").mkdir(parents=True)
    (src / "zapret-winws" / "new.txt").write_text("new")
    dest = tmp_path / "zapret-win-bundle"
    (dest / "zapret-winws").mkdir(parents=True)
    (dest / "zapret-winws" / "stale.txt").write_text("old")

    fetch_bins.copy_winws(src, dest)

    assert (dest / "zapret-winws" / "new.txt").exists()
    assert not (dest / "zapret-winws" / "stale.txt").exists()


def test_check_sha():
    blob = b"sing-box"
    fetch_bins.check_sha(blob, hashlib.sha256(blob).hexdigest())
    with pytest.raises(RuntimeError, match="SHA256"):
        fetch_bins.check_sha(blob, "0" * 64)


def test_bundle_commit_is_full_hash():
    assert len(fetch_bins.BUNDLE_COMMIT) == 40


def test_manifest_flag_lists_build_files(tmp_path):
    # build.bat зовёт это последним шагом — самообновление по этому списку отличает свои файлы от чужих
    (tmp_path / "bin").mkdir()
    (tmp_path / "Chimera.exe").write_bytes(b"exe")
    (tmp_path / "bin" / "x.dll").write_bytes(b"dll")
    assert fetch_bins.main(["--manifest", str(tmp_path)]) == 0
    lines = (tmp_path / "manifest.txt").read_text(encoding="utf-8").split()
    assert lines == ["Chimera.exe", "bin/x.dll"]


def test_qt_runtime_replaces_old_msvcp_in_build(tmp_path):
    # Nuitka кладёт msvcp140 от VS2019 (14.29), а Qt 6.11 собран новее и на ней падает
    # рендерер QtWebEngine (0xC0000005 — пустое окно). В сборку идут копии из PySide6.
    qt, build = tmp_path / "PySide6", tmp_path / "build"
    qt.mkdir()
    build.mkdir()
    for name in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll"):
        (qt / name).write_bytes(b"new")
        (build / name).write_bytes(b"old")
    (qt / "Qt6Core.dll").write_bytes(b"qt")  # не runtime — не трогаем
    copied = fetch_bins.use_qt_runtime(build, qt)
    assert sorted(copied) == ["msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll"]
    assert all((build / n).read_bytes() == b"new" for n in copied)
    assert not (build / "Qt6Core.dll").exists()


def test_write_versions_pins_bundle_commit(tmp_path, monkeypatch):
    # версии тегов берутся из рабочей копии; бандл — пиннутый коммит, а не то, что лежит в bin/
    monkeypatch.setattr(fetch_bins.upstream, "_current", lambda src: f"cur-{src['kind']}")
    out = tmp_path / "versions.json"
    fetch_bins.write_versions(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["winws-бандл (bol-van)"] == fetch_bins.BUNDLE_COMMIT[:7]
    assert data["Движок zapret2 (winws2)"] == "cur-tag"
    assert "Python" not in data  # не git-источники в файл не пишутся
