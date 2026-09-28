"""modules/winproc.py — быстрые WinAPI-запросы вместо tasklist/Get-Service.

Разбор структур (ToolHelp32Snapshot, SCM) можно честно проверить только на
живой Windows — на другой платформе модуль и не соберётся (windll есть только
у Windows-сборки Python). Сверяем результат с эталонными системными командами,
благо они точно есть на любой Windows.
"""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="ctypes.windll — только Windows")

from modules import winproc  # noqa: E402 - после skipif


def _tasklist_pids(name: str) -> list[int]:
    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    pids = []
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 2 and cols[0].lower() == name.lower():
            try:
                pids.append(int(cols[1]))
            except ValueError:
                pass
    return pids


def test_pids_by_name_matches_tasklist_for_running_process():
    # explorer.exe гарантированно живёт в любой интерактивной сессии Windows
    assert sorted(winproc.pids_by_name("explorer.exe")) == sorted(_tasklist_pids("explorer.exe"))


def test_pids_by_name_unknown_process_is_empty():
    assert winproc.pids_by_name("no-such-process-chimera-test.exe") == []


def test_pids_by_name_case_insensitive():
    lower = winproc.pids_by_name("explorer.exe")
    upper = winproc.pids_by_name("EXPLORER.EXE")
    assert sorted(lower) == sorted(upper)


def _get_service_status(name: str) -> str | None:
    ps = (
        f"$s=Get-Service -Name '{name}' -ErrorAction SilentlyContinue;"
        "if(-not $s){'NONE'}else{[string]$s.Status}"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout.strip()
    return None if out in ("", "NONE") else out


def test_service_status_matches_get_service_for_known_service():
    # Spooler стоит на любой обычной Windows-машине (может быть Stopped, но не отсутствовать).
    # winproc.service_status возвращает 'RUNNING'/'STOPPED' (свой контракт, как у
    # _divert_status) — Get-Service отдаёт enum 'Running'/'Stopped', сверяем без учёта регистра.
    ps_status = _get_service_status("Spooler")
    if ps_status is None:
        pytest.skip("службы Spooler нет на этой машине")
    assert winproc.service_status("Spooler").lower() == ps_status.lower()


def test_service_status_unknown_service_is_none():
    assert winproc.service_status("no-such-service-chimera-test") is None
