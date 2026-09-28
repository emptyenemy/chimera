"""Автозапуск с Windows: что именно запускает задача планировщика."""

import sys

from modules import autostart, paths, service


def test_launch_target_frozen_runs_exe_directly(monkeypatch):
    # сборка Nuitka не ставит sys.frozen — признак берётся из paths.IS_FROZEN
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    command, _ = autostart._launch_target()
    assert command == sys.executable


def test_launch_target_from_sources_runs_main_py(monkeypatch):
    monkeypatch.setattr(paths, "IS_FROZEN", False)
    command, arguments = autostart._launch_target()
    assert command.lower().endswith(("pythonw.exe", "python.exe"))
    assert str(autostart.MAIN_PY) in arguments


def test_service_launch_target_frozen_runs_exe_directly(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    assert service._launch_target() == (sys.executable, "service run")
