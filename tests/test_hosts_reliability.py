"""hosts, который на миг занят другим процессом, и запись, которая не удалась.

Служба DNS-клиента перечитывает hosts сразу после правки, Defender его проверяет: в эти доли
секунды файл открыт без права записи, и open('w') падает с «Permission denied» даже у
администратора. Блокировка здесь настоящая — тот же CreateFileW с доступом только на чтение.
"""

import ctypes
import sys
import threading
import time
from ctypes import wintypes as w

import pytest

from modules.errors import ChimeraPermissionError
from modules.hosts import manager as hosts_manager
from modules.hosts.manager import BEGIN_MARK, HostsManager

windows = pytest.mark.skipif(sys.platform != "win32", reason="блокировка файла — Windows")


def hold(path, seconds):
    """Держит файл открытым только на чтение, как DNS-клиент; отпускает через seconds."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = w.HANDLE
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    handle = k.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
    assert handle not in (None, w.HANDLE(-1).value)
    timer = threading.Timer(seconds, lambda: k.CloseHandle(handle))
    timer.start()
    return timer


@pytest.fixture
def hm(tmp_path, monkeypatch):
    hosts_path = tmp_path / "hosts"
    hosts_path.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    monkeypatch.setattr(hosts_manager.subprocess, "run", lambda *a, **kw: None)
    monkeypatch.setattr(hosts_manager, "is_admin", lambda: True)
    monkeypatch.setattr(hosts_manager, "split_lists", lambda names: (["example.com"], []))
    monkeypatch.setattr(hosts_manager, "resolve_domains",
                        lambda domains, doh, servers: [{"ip": "9.9.9.9", "host": d} for d in domains])
    manager = HostsManager(state_path=tmp_path / "state.json", hosts_path=hosts_path)
    monkeypatch.setattr(manager, "get_provider", lambda pid: {"id": pid, "name": pid, "doh": None, "servers": []})
    return manager


@windows
def test_a_briefly_held_hosts_file_is_written_once_it_is_released(hm):
    timer = hold(hm.hosts_path, 0.3)
    started = time.monotonic()
    hm.set_assignments({"xbox": ["discord"]})
    timer.join()
    assert hm._is_applied() and time.monotonic() - started >= 0.25
    assert hm.hosts_path.read_text(encoding="utf-8").startswith("127.0.0.1 localhost\n")


@windows
def test_a_file_held_too_long_is_reported_and_left_intact(hm, monkeypatch):
    monkeypatch.setattr(hosts_manager.time, "sleep", lambda s: None)
    timer = hold(hm.hosts_path, 0.5)
    with pytest.raises(ChimeraPermissionError) as error:
        hm.set_assignments({"xbox": ["discord"]})
    timer.join()
    assert error.value.code == "err.hosts.manager.busy"
    assert hm.hosts_path.read_text(encoding="utf-8") == "127.0.0.1 localhost\n"


def test_a_failed_write_keeps_the_previous_state(hm, monkeypatch):
    # «Выключить всё» не смогло снять блок — программа не должна считать hosts выключенным
    hm.set_assignments({"xbox": ["discord"]})

    def busy(text):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(hm, "_write_hosts", busy)
    with pytest.raises(PermissionError):
        hm.set_enabled(False)
    state = hm.state()
    assert state["enabled"] is True and state["applied"] is True and state["count"] == 1


def test_a_failed_resolve_keeps_the_previous_assignments(hm, monkeypatch):
    hm.set_assignments({"xbox": ["discord"]})
    monkeypatch.setattr(hosts_manager, "resolve_domains", lambda domains, doh, servers: [])
    with pytest.raises(ValueError):
        hm.set_assignments({"comss": ["youtube"]})
    assert hm.assignments() == {"xbox": ["discord"]}
    assert BEGIN_MARK in hm.hosts_path.read_text(encoding="utf-8")


def test_turning_on_repairs_a_block_left_while_marked_off(hm):
    # так выглядело у пользователя: выключено, а блок в hosts остался после сорванной записи
    hm.set_assignments({"xbox": ["discord"]})
    state = hm._load_state()
    state["enabled"] = False
    hm._save_state(state)
    assert hm.state()["applied"] is True
    assert hm.set_enabled(False)["applied"] is False    # повторное «выключить» снимает блок
    assert hm.set_enabled(True)["applied"] is True
