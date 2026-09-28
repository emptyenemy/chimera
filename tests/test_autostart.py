"""Автозапуск с Windows: что именно запускает задача планировщика."""

import sys
from types import SimpleNamespace

from modules import autostart, paths, service


def test_launch_target_frozen_runs_exe_directly(monkeypatch):
    # сборка Nuitka не ставит sys.frozen — признак берётся из paths.IS_FROZEN
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    command, arguments = autostart._launch_target()
    assert command == sys.executable
    assert arguments == autostart.TRAY_ARG


def test_launch_target_from_sources_runs_main_py(monkeypatch):
    monkeypatch.setattr(paths, "IS_FROZEN", False)
    command, arguments = autostart._launch_target()
    assert command.lower().endswith(("pythonw.exe", "python.exe"))
    assert str(autostart.MAIN_PY) in arguments
    # с Windows — сразу в трей, без окна
    assert arguments.endswith(autostart.TRAY_ARG)


def _task_query_xml(command: str, arguments: str) -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>\n<Task><Actions Context="Author"><Exec>'
        f"<Command>{command}</Command><Arguments>{arguments}</Arguments>"
        "</Exec></Actions></Task>\n"
    )
    return xml.encode("utf-16")


class _Run:
    """Подмена subprocess.run: /Query /XML отдаёт заданную задачу, /Create запоминается."""

    def __init__(self, xml: bytes | None):
        self.xml = xml
        self.created = False

    def __call__(self, args, **kw):
        if "/Create" in args:
            self.created = True
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "/XML" in args:
            if self.xml is None:
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            return SimpleNamespace(returncode=0, stdout=self.xml, stderr=b"")
        return SimpleNamespace(returncode=0 if self.xml is not None else 1, stdout=b"", stderr=b"")


def test_refresh_recreates_task_with_old_arguments(monkeypatch):
    # задача из версии до трея — без --tray: пересоздаём, чтобы старт шёл сразу в трей
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    run = _Run(_task_query_xml(sys.executable, ""))
    monkeypatch.setattr(autostart.subprocess, "run", run)
    assert autostart.refresh() is True
    assert run.created


def test_refresh_keeps_up_to_date_task(monkeypatch):
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    run = _Run(_task_query_xml(sys.executable, autostart.TRAY_ARG))
    monkeypatch.setattr(autostart.subprocess, "run", run)
    assert autostart.refresh() is False
    assert not run.created


def test_refresh_understands_quoted_arguments_from_scheduler(monkeypatch):
    # из исходников аргументы — путь к main.py в кавычках; планировщик отдаёт их как &quot;
    monkeypatch.setattr(paths, "IS_FROZEN", False)
    command, arguments = autostart._launch_target()
    run = _Run(_task_query_xml(command, arguments.replace('"', "&quot;")))
    monkeypatch.setattr(autostart.subprocess, "run", run)
    assert autostart.refresh() is False
    assert not run.created


def test_refresh_does_nothing_without_task(monkeypatch):
    run = _Run(None)
    monkeypatch.setattr(autostart.subprocess, "run", run)
    assert autostart.refresh() is False
    assert not run.created


def test_api_autostart_set_keeps_supported_flag(monkeypatch):
    # фронт заменяет состояние ответом целиком: без supported тумблер становился
    # неактивным и второй раз не переключался до перезапуска программы
    from ui import api as api_mod
    monkeypatch.setattr(api_mod, "is_admin", lambda: True)
    monkeypatch.setattr(api_mod.autostart, "set_enabled", lambda v: v)
    monkeypatch.setattr(api_mod.autostart, "is_supported", lambda: True)
    res = api_mod.Api.autostart_set(None, True)
    assert res == {"ok": True, "data": {"enabled": True, "supported": True}}


def test_service_launch_target_frozen_runs_exe_directly(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    assert service._launch_target() == (sys.executable, "service run")
