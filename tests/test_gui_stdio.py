from types import SimpleNamespace
from unittest.mock import Mock

from modules import gui_stdio


def test_valid_redirected_handles_are_preserved(monkeypatch):
    kernel = SimpleNamespace(GetStdHandle=Mock(return_value=99), GetFileType=Mock(return_value=3), SetStdHandle=Mock())
    monkeypatch.setattr(gui_stdio.ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    before = gui_stdio.sys.stdin, gui_stdio.sys.stdout, gui_stdio.sys.stderr
    gui_stdio.prepare()
    assert (gui_stdio.sys.stdin, gui_stdio.sys.stdout, gui_stdio.sys.stderr) == before
    kernel.SetStdHandle.assert_not_called()


def test_gui_without_handles_gets_usable_subprocess_streams(monkeypatch):
    kernel = SimpleNamespace(GetStdHandle=Mock(return_value=None), GetFileType=Mock(), SetStdHandle=Mock(return_value=True))
    monkeypatch.setattr(gui_stdio.ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    monkeypatch.setattr(gui_stdio, "_streams", [])
    for name in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(gui_stdio.sys, name, None)
        monkeypatch.setattr(gui_stdio.sys, f"__{name}__", None)
    try:
        gui_stdio.prepare()
        assert kernel.SetStdHandle.call_count == 3
        assert gui_stdio.sys.stdin.read() == ""
        assert gui_stdio.sys.stdout.write("valid handle") == 12
        assert all(stream.fileno() >= 0 for stream in gui_stdio._streams)
    finally:
        for stream in gui_stdio._streams:
            stream.close()
