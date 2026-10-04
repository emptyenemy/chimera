"""Чужой sing-box (другая программа, другая папка) не останавливается и не перезапускается."""

import pytest

from modules.proxy import manager as proxy_manager
from modules.proxy.manager import SINGBOX_EXE, ProxyManager

VLESS = "vless://11111111-1111-1111-1111-111111111111@a.example:443?security=tls&sni=a.example#A"


@pytest.fixture
def procs(monkeypatch, tmp_path):
    monkeypatch.setattr(proxy_manager, "STATE_PATH", tmp_path / "proxy.json")
    table = {}   # pid -> путь к exe
    monkeypatch.setattr(ProxyManager, "_system_pids", staticmethod(lambda: list(table)))
    monkeypatch.setattr(proxy_manager.winproc, "image_path", lambda pid: table.get(pid))
    killed = []

    def taskkill(argv, **kwargs):
        if "/PID" not in argv:           # прочие вызовы (версия ядра) к делу не относятся
            return proxy_manager.subprocess.CompletedProcess(argv, 1, "", "")
        pid = int(argv[argv.index("/PID") + 1])
        killed.append(pid)
        table.pop(pid, None)

    monkeypatch.setattr(proxy_manager.subprocess, "run", taskkill)
    return table, killed


def test_only_our_own_leftover_is_killed(procs):
    table, killed = procs
    table[100] = str(SINGBOX_EXE.resolve())
    table[200] = r"C:\Program Files\Hiddify\sing-box.exe"
    table[300] = None                       # путь не узнать — тоже не трогаем
    ProxyManager._kill_leftovers()
    assert killed == [100] and set(table) == {200, 300}


def test_changing_the_link_does_not_start_ours_over_a_foreign_client(procs, monkeypatch):
    table, _ = procs
    table[200] = r"C:\Program Files\Hiddify\sing-box.exe"
    pm = ProxyManager()
    restarted = []
    monkeypatch.setattr(pm, "restart", lambda: restarted.append(True))
    assert pm.running is True and pm._restartable is False   # видно, что работает, но не наш
    pm.set_link(VLESS)
    pm.set_mode("tun")
    assert restarted == []


def test_our_leftover_is_restarted_with_the_new_link(procs, monkeypatch):
    table, _ = procs
    table[100] = str(SINGBOX_EXE.resolve())
    pm = ProxyManager()
    restarted = []
    monkeypatch.setattr(pm, "restart", lambda: restarted.append(True))
    pm.set_link(VLESS)
    assert restarted == [True]
