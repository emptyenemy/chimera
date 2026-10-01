from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import smoke_launch


@pytest.mark.parametrize("opened", [True, False])
def test_shell_launch_has_no_arguments_or_console_streams_and_restores_runner(monkeypatch, tmp_path, opened):
    original = {-10: 110, -11: 111, -12: 112}
    active = dict(original)
    kernel = SimpleNamespace(GetProcessId=Mock(return_value=123), GetExitCodeProcess=Mock(),
                             CloseHandle=Mock(), GetStdHandle=Mock(side_effect=active.get),
                             SetStdHandle=Mock(side_effect=lambda kind, value: active.update({kind: value})))

    def execute(pointer):
        assert active == {-10: None, -11: None, -12: None}
        info = pointer._obj
        assert info.lpVerb == "open" and info.lpParameters is None and info.nShow == 1
        info.hProcess = 42
        return opened

    shell = SimpleNamespace(ShellExecuteExW=Mock(side_effect=execute))
    monkeypatch.setattr(smoke_launch.ctypes, "WinDLL", lambda name, **kwargs: kernel if name == "kernel32" else shell)
    if opened:
        process = smoke_launch.ShellProcess(tmp_path / "Chimera.exe")
        assert process.pid == 123 and process.handle == 42
    else:
        with pytest.raises(OSError):
            smoke_launch.ShellProcess(tmp_path / "Chimera.exe")
    assert active == original


def test_reused_parent_pid_does_not_claim_older_processes(monkeypatch):
    rows = iter([(10, 4, "Chimera.exe"), (20, 10, "old-browser.exe"),
                 (21, 20, "old-helper.exe"), (30, 10, "msedge.exe"), (31, 30, "renderer.exe")])

    def next_process(handle, pointer):
        row = next(rows, None)
        if row is None:
            return False
        pointer._obj.pid, pointer._obj.parent, pointer._obj.exe = row
        return True

    kernel = SimpleNamespace(CreateToolhelp32Snapshot=Mock(return_value=42),
                             Process32FirstW=Mock(side_effect=next_process),
                             Process32NextW=Mock(side_effect=next_process), CloseHandle=Mock())
    monkeypatch.setattr(smoke_launch.ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    times = {10: 100, 20: 10, 21: 20, 30: 110, 31: 120}
    monkeypatch.setattr(smoke_launch, "creation_time", times.get)
    assert smoke_launch.processes(10) == [(10, "Chimera.exe"), (30, "msedge.exe"), (31, "renderer.exe")]
