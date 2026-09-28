"""Самообновление: выбор релиза, проверка, скачивание, распаковка и apply.cmd."""

import ctypes
import hashlib
import io
import os
import subprocess
import sys
import urllib.error
import zipfile
from ctypes import wintypes

import pytest

from modules import selfupdate


def _asset(version, digest=True):
    blob = f"zip-{version}".encode()
    a = {"name": f"Chimera-{version}-win64.zip", "browser_download_url": f"https://x/{version}.zip",
         "size": len(blob)}
    if digest:
        a["digest"] = "sha256:" + hashlib.sha256(blob).hexdigest()
    return a


def _release(tag, prerelease=False, draft=False, assets=None):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "body": f"изменения {tag}",
            "html_url": f"https://github.com/emptyenemy/chimera/releases/tag/{tag}",
            "assets": [_asset(tag.lstrip("v"))] if assets is None else assets}


# --- выбор релиза -----------------------------------------------------------------

def test_pick_skips_drafts_and_prereleases_on_stable():
    releases = [_release("v0.4.0", draft=True), _release("v0.3.0-beta.1", prerelease=True), _release("v0.2.0")]
    assert selfupdate.pick_release(releases, "stable")["tag_name"] == "v0.2.0"


def test_pick_beta_takes_prerelease_when_newest():
    releases = [_release("v0.3.0-beta.1", prerelease=True), _release("v0.2.0")]
    assert selfupdate.pick_release(releases, "beta")["tag_name"] == "v0.3.0-beta.1"


def test_pick_by_version_not_by_order():
    # GitHub отдаёт по дате создания; хотфикс старой ветки может оказаться первым
    releases = [_release("v0.1.5"), _release("v0.2.0")]
    assert selfupdate.pick_release(releases, "stable")["tag_name"] == "v0.2.0"


def test_pick_skips_release_without_zip_asset():
    releases = [_release("v0.3.0", assets=[{"name": "notes.txt"}]), _release("v0.2.0")]
    assert selfupdate.pick_release(releases, "stable")["tag_name"] == "v0.2.0"


def test_pick_nothing():
    assert selfupdate.pick_release([], "stable") is None
    assert selfupdate.pick_release([_release("nightly")], "beta") is None


# --- проверка ---------------------------------------------------------------------

def _fetch(releases):
    return lambda url: releases


@pytest.fixture
def frozen_app(tmp_path, monkeypatch):
    """Собранная программа с manifest.txt — как её распаковали из релиза."""
    (tmp_path / "Chimera.exe").write_text("exe", encoding="utf-8")
    selfupdate.write_manifest(tmp_path)
    monkeypatch.setattr(selfupdate.paths, "IS_FROZEN", True)
    monkeypatch.setattr(selfupdate.paths, "APP_DIR", tmp_path)
    return tmp_path


def test_check_finds_update(frozen_app):
    res = selfupdate.check("stable", current="0.1.0", fetch=_fetch([_release("v0.2.0")]))
    assert res["update"] is True and res["installable"] is True and res["error"] is None
    assert res["latest"] == "0.2.0"
    assert res["asset"]["sha256"] == hashlib.sha256(b"zip-0.2.0").hexdigest()
    assert res["notes"] == "изменения v0.2.0"


def test_check_without_manifest_is_not_installable(frozen_app):
    # сборка без списка своих файлов — ставить поверх нельзя (см. write_script)
    (frozen_app / selfupdate.MANIFEST).unlink()
    res = selfupdate.check("stable", current="0.1.0", fetch=_fetch([_release("v0.2.0")]))
    assert res["update"] is True and res["installable"] is False


def test_check_up_to_date(frozen_app):
    res = selfupdate.check("stable", current="0.2.0", fetch=_fetch([_release("v0.2.0")]))
    assert res["update"] is False and res["installable"] is False and res["error"] is None


def test_check_from_sources_is_not_installable(monkeypatch):
    monkeypatch.setattr(selfupdate.paths, "IS_FROZEN", False)
    res = selfupdate.check("stable", current="dev", fetch=_fetch([_release("v0.2.0")]))
    assert res["update"] is True
    assert res["installable"] is False  # из исходников — только через git


def test_check_without_digest_is_not_installable(frozen_app):
    # без контрольной суммы ставить нельзя: не с чем сверить скачанное
    rel = _release("v0.2.0", assets=[_asset("0.2.0", digest=False)])
    res = selfupdate.check("stable", current="0.1.0", fetch=_fetch([rel]))
    assert res["update"] is True and res["installable"] is False


def test_check_private_repo_404():
    def fetch(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    res = selfupdate.check("stable", current="0.1.0", fetch=fetch)
    assert res["update"] is False and res["installable"] is False
    assert "не удалось проверить" in res["error"]


def test_check_no_network():
    def fetch(url):
        raise urllib.error.URLError("no route")
    res = selfupdate.check("stable", current="0.1.0", fetch=fetch)
    assert res["update"] is False and "не удалось проверить" in res["error"]


# --- скачивание -------------------------------------------------------------------

class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _asset_info(data, sha=None):
    return {"name": "Chimera-0.2.0-win64.zip", "url": "https://x/a.zip", "size": len(data),
            "sha256": sha or hashlib.sha256(data).hexdigest()}


def test_download_ok_reports_progress(tmp_path):
    data = b"x" * 700_000
    seen = []
    path = selfupdate.download(_asset_info(data), tmp_path, progress=lambda d, t: seen.append((d, t)),
                               opener=lambda req, timeout=None: _Resp(data))
    assert path.read_bytes() == data
    assert seen[-1] == (len(data), len(data))
    assert not list(tmp_path.glob("*.part"))


def test_download_sha_mismatch_leaves_nothing(tmp_path):
    data = b"tampered"
    with pytest.raises(RuntimeError, match="SHA256"):
        selfupdate.download(_asset_info(data, sha="0" * 64), tmp_path,
                            opener=lambda req, timeout=None: _Resp(data))
    assert list(tmp_path.iterdir()) == []


# --- распаковка -------------------------------------------------------------------

def test_stage_returns_folder_with_exe(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Chimera/Chimera.exe", b"exe")
        f.writestr("Chimera/ui/web/index.html", b"<html>")
    staged = selfupdate.stage(z, tmp_path / "staged")
    assert (staged / "Chimera.exe").read_bytes() == b"exe"
    assert (staged / "ui" / "web" / "index.html").exists()


def test_stage_rejects_broken_zip(tmp_path):
    z = tmp_path / "a.zip"
    z.write_bytes(b"not a zip at all")
    with pytest.raises(RuntimeError):
        selfupdate.stage(z, tmp_path / "staged")


def test_stage_rejects_zip_without_exe(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Chimera/readme.txt", b"x")
    with pytest.raises(RuntimeError, match="Chimera.exe"):
        selfupdate.stage(z, tmp_path / "staged")


# --- apply.cmd --------------------------------------------------------------------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe и robocopy")


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _finished_pid():
    p = subprocess.Popen(["cmd", "/c", "exit"], creationflags=subprocess.CREATE_NO_WINDOW)
    p.wait()
    return p.pid


@pytest.fixture
def layout(tmp_path):
    # пробел и кириллица в пути — как у «C:\Program Files\Чимера»
    app = tmp_path / "Программа Chimera"
    # файлы релиза — то, что пришло из архива (их и перечисляет manifest.txt сборки)
    _write(app / "Chimera.exe", "old exe")
    _write(app / "old_only.txt", "удалить при обновлении")
    _write(app / "strategies" / "hostlists" / "list-general.txt", "старый общий список")
    selfupdate.write_manifest(app)
    # а это появилось уже у пользователя — в манифесте его нет
    _write(app / "data" / "state.json", "state")
    _write(app / "config.json", "мой конфиг")
    _write(app / "strategies" / "hostlists" / "list-general-user.txt", "мои домены")
    _write(app / "strategies" / "hostlists" / "ipset-all.txt", "мой ipset")
    staged = tmp_path / "update" / "staged" / "Chimera"
    _write(staged / "Chimera.exe", "new exe")
    _write(staged / "new.txt", "новое")
    _write(staged / "strategies" / "hostlists" / "list-general.txt", "общий список")
    _write(staged / "lib" / "config.json", "файл пакета, тёзка config.json")  # не путать с настройками
    selfupdate.write_manifest(staged)
    return app, staged, tmp_path / "update"


def _run_script(app, staged, upd):
    script = selfupdate.write_script(app, staged, _finished_pid(), restart_service=False, relaunch=False,
                                     script=upd / "apply.cmd", log=upd / "update.log",
                                     rollback=upd / "rollback")
    r = subprocess.run(["cmd", "/c", str(script)], capture_output=True, timeout=120,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return r, (upd / "update.log").read_text(encoding="utf-8", errors="replace")


@windows_only
def test_apply_script_updates_and_keeps_user_files(layout):
    app, staged, upd = layout
    r, log = _run_script(app, staged, upd)
    assert r.returncode == 0, log
    assert (app / "Chimera.exe").read_text(encoding="utf-8") == "new exe"
    assert (app / "new.txt").exists()
    assert not (app / "old_only.txt").exists()
    assert (app / "lib" / "config.json").exists()
    assert (app / "data" / "state.json").read_text(encoding="utf-8") == "state"
    assert (app / "config.json").read_text(encoding="utf-8") == "мой конфиг"
    assert (app / "strategies" / "hostlists" / "list-general-user.txt").read_text(encoding="utf-8") == "мои домены"
    assert (app / "strategies" / "hostlists" / "ipset-all.txt").exists()
    assert (app / "strategies" / "hostlists" / "list-general.txt").exists()
    assert "готово" in log


@windows_only
def test_apply_script_keeps_unrelated_files_next_to_program(layout):
    # программу распаковали не в свою папку, а, скажем, на рабочий стол — чужие файлы
    # рядом не принадлежат Chimera и обновление не должно их трогать
    app, staged, upd = layout
    _write(app / "мои документы.txt", "не удалять")
    _write(app / "Фото" / "отпуск.jpg", "jpg")
    r, log = _run_script(app, staged, upd)
    assert r.returncode == 0, log
    assert (app / "мои документы.txt").read_text(encoding="utf-8") == "не удалять"
    assert (app / "Фото" / "отпуск.jpg").exists()


@windows_only
def test_apply_script_keeps_user_edits_in_lists(tmp_path):
    # списки правят прямо в программе: обновление добавляет новые, но не трогает лежащие
    app, staged, upd = tmp_path / "app", tmp_path / "update" / "staged" / "Chimera", tmp_path / "update"
    _write(app / "Chimera.exe", "old")
    _write(app / "lists" / "google-gemini.txt", "как в релизе 1.0")
    _write(app / "lists" / "removed.txt", "убран из следующего релиза")
    selfupdate.write_manifest(app)
    _write(app / "lists" / "google-gemini.txt", "поправлено пользователем")
    _write(app / "lists" / "mine.txt", "свой список")
    _write(staged / "Chimera.exe", "new")
    _write(staged / "lists" / "google-gemini.txt", "как в релизе 1.1")
    _write(staged / "lists" / "fresh.txt", "новый список релиза")
    selfupdate.write_manifest(staged)
    r, log = _run_script(app, staged, upd)
    assert r.returncode == 0, log
    assert (app / "Chimera.exe").read_text(encoding="utf-8") == "new"
    assert (app / "lists" / "google-gemini.txt").read_text(encoding="utf-8") == "поправлено пользователем"
    assert (app / "lists" / "fresh.txt").exists()
    assert (app / "lists" / "mine.txt").exists()
    assert (app / "lists" / "removed.txt").exists()


@windows_only
def test_apply_script_replaces_file_with_same_size_and_time(tmp_path):
    # robocopy по умолчанию считает файлы одинаковыми по размеру и времени; новая версия
    # с тем же размером и той же датой (тот же день сборки, округление времени в zip)
    # всё равно должна лечь поверх старой
    app, staged, upd = tmp_path / "app", tmp_path / "update" / "staged" / "Chimera", tmp_path / "update"
    _write(app / "Chimera.exe", "old")
    selfupdate.write_manifest(app)
    _write(staged / "Chimera.exe", "new")
    selfupdate.write_manifest(staged)
    stamp = 1_700_000_000
    os.utime(app / "Chimera.exe", (stamp, stamp))
    os.utime(staged / "Chimera.exe", (stamp, stamp))
    r, log = _run_script(app, staged, upd)
    assert r.returncode == 0, log
    assert (app / "Chimera.exe").read_text(encoding="utf-8") == "new"


def _lock(path, share):
    """Открывает файл с заданным режимом общего доступа: 0 — никому, 1 — только чтение."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    h = k32.CreateFileW(str(path), 0x80000000, share, None, 3, 0x80, None)  # GENERIC_READ, OPEN_EXISTING
    assert h not in (None, wintypes.HANDLE(-1).value)
    return lambda: k32.CloseHandle(h)


@windows_only
def test_apply_script_rolls_back_when_copy_fails(layout):
    app, staged, upd = layout
    # читать можно (текущая версия сохранится), перезаписать нельзя — ставка новой упадёт
    unlock = _lock(app / "Chimera.exe", share=1)
    try:
        r, log = _run_script(app, staged, upd)
    finally:
        unlock()
    assert r.returncode != 0
    assert "откат" in log
    assert (app / "Chimera.exe").read_text(encoding="utf-8") == "old exe"
    assert (app / "old_only.txt").exists()
    assert (app / "strategies" / "hostlists" / "list-general.txt").read_text(encoding="utf-8") == "старый общий список"
    assert not (app / "new.txt").exists()       # частично скопированное новое убрано
    assert not (app / "lib" / "config.json").exists()
    assert (app / "config.json").read_text(encoding="utf-8") == "мой конфиг"
    assert (app / "data" / "state.json").exists()


@windows_only
def test_rollback_keeps_unrelated_files_next_to_program(layout):
    app, staged, upd = layout
    _write(app / "мои документы.txt", "не удалять")
    unlock = _lock(app / "Chimera.exe", share=1)
    try:
        r, log = _run_script(app, staged, upd)
    finally:
        unlock()
    assert "откат" in log
    assert (app / "мои документы.txt").read_text(encoding="utf-8") == "не удалять"


@windows_only
def test_nothing_changes_when_current_version_cannot_be_saved(layout):
    app, staged, upd = layout
    # файл не читается вовсе — без копии для отката новую версию не ставим, и это
    # выясняется ещё до выхода программы: она продолжает работать как была
    unlock = _lock(app / "Chimera.exe", share=0)
    try:
        with pytest.raises(RuntimeError, match="сохранить текущую версию"):
            _run_script(app, staged, upd)
    finally:
        unlock()
    assert not (upd / "apply.cmd").exists()
    assert (app / "Chimera.exe").read_text(encoding="utf-8") == "old exe"
    assert not (app / "new.txt").exists()


def test_write_script_refuses_install_without_manifest(tmp_path):
    # без списка файлов релиза не отличить свои файлы от чужих — не трогаем ничего
    app, staged = tmp_path / "app", tmp_path / "staged"
    _write(app / "Chimera.exe", "old")
    _write(staged / "Chimera.exe", "new")
    with pytest.raises(RuntimeError, match="manifest"):
        selfupdate.write_script(app, staged, 1, restart_service=False, relaunch=False,
                                script=tmp_path / "a.cmd", log=tmp_path / "u.log", rollback=tmp_path / "rb")


def test_write_manifest_lists_all_files_relative(tmp_path):
    _write(tmp_path / "Chimera.exe", "x")
    _write(tmp_path / "bin" / "sing-box" / "sing-box.exe", "y")
    files = selfupdate.write_manifest(tmp_path)
    assert files == ["Chimera.exe", "bin/sing-box/sing-box.exe"]
    assert selfupdate.read_manifest(tmp_path) == set(files)
