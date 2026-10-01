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
