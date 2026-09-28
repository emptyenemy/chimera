"""Куда идёт запуск: командная строка или окно (modules/cli/entry.py и main.py)."""

import sys

import pytest

import main as main_module
from modules import autostart, paths
from modules.cli import commands, entry, registry

# --- решение о маршруте ------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--window"], ["--browser"], ["--tray"], ["--window", "--tray"],
                                  ["--tray", "--window"]])
def test_window_flags_open_the_window(argv):
    assert entry.route(argv, frozen=True, console=True) == "gui"


@pytest.mark.parametrize("argv", [["status"], ["--help"], ["--version"], ["winws", "start"], ["service", "run"],
                                  ["docs", "--json"]])
def test_other_arguments_go_to_the_command_line(argv):
    assert entry.route(argv, frozen=True, console=False) == "cli"
    assert entry.route(argv, frozen=False, console=True) == "cli"


def test_double_click_on_the_exe_opens_the_window():
    # собранный exe без аргументов и без консоли-родителя: проводник, ярлык, автозапуск старого вида
    assert entry.route([], frozen=True, console=False) == "gui"


def test_exe_without_arguments_in_a_terminal_prints_help():
    assert entry.route([], frozen=True, console=True) == "cli"


def test_running_from_source_without_arguments_still_opens_the_window():
    assert entry.route([], frozen=False, console=True) == "gui"


def test_forced_window_and_backend_override():
    assert entry.forces_window(["--window"]) and entry.forces_window(["--browser"])
    assert not entry.forces_window(["--tray"]) and not entry.forces_window([])
    assert entry.backend_override(["--browser"]) == "browser"
    assert entry.backend_override(["--window"]) is None


# --- main.main() -----------------------------------------------------------------------------------------

class _NoTimer:
    def __init__(self, *a, **kw):
        self.daemon = False

    def start(self):
        pass


@pytest.fixture
def gui(monkeypatch):
    """Подменяем всё, что открыло бы настоящее окно, и запоминаем вызовы."""
    calls = []
    import ui.app
    monkeypatch.setattr(ui.app, "run", lambda backend=None: calls.append(("ui", backend)))
    monkeypatch.setattr(main_module, "is_admin", lambda: True)
    monkeypatch.setattr(main_module.threading, "Timer", _NoTimer)
    from modules import instance
    monkeypatch.setattr(instance, "is_running", lambda: False)
    monkeypatch.setattr(main_module, "load_config", lambda: {"interface": "ui", "auto_elevate": True})
    return calls


def test_main_runs_the_command_line_for_commands(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["chimera", "--version"])
    monkeypatch.setattr(entry, "has_console", lambda: True)
    assert main_module.main() == 0
    assert "Chimera" in capsys.readouterr().out


def test_main_does_not_ask_for_admin_rights_for_commands(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["chimera", "docs"])
    monkeypatch.setattr(main_module, "is_admin", lambda: False)
    monkeypatch.setattr(main_module, "relaunch_as_admin", lambda: pytest.fail("UAC для команды не нужен"))
    assert main_module.main() == 0


def test_main_opens_window_for_window_flag(monkeypatch, gui):
    monkeypatch.setattr(sys, "argv", ["chimera", "--window", "--tray"])
    assert main_module.main() == 0
    assert gui == [("ui", None)]


def test_main_opens_browser_backend_for_browser_flag(monkeypatch, gui):
    monkeypatch.setattr(sys, "argv", ["chimera", "--browser"])
    assert main_module.main() == 0
    assert gui == [("ui", "browser")]


def test_window_flag_overrides_interface_mode_from_config(monkeypatch, gui):
    monkeypatch.setattr(main_module, "load_config", lambda: {"interface": "tui", "auto_elevate": True})
    monkeypatch.setattr(sys, "argv", ["chimera", "--window"])
    assert main_module.main() == 0
    assert gui == [("ui", None)]


def test_legacy_tray_argument_alone_still_opens_the_window(monkeypatch, gui):
    # задача автозапуска из прошлой версии зовёт exe с одним --tray
    monkeypatch.setattr(sys, "argv", ["Chimera.exe", "--tray"])
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(entry, "has_console", lambda: True)
    assert main_module.main() == 0
    assert gui == [("ui", None)]


def test_double_click_in_frozen_exe_opens_window(monkeypatch, gui):
    monkeypatch.setattr(sys, "argv", ["Chimera.exe"])
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(entry, "has_console", lambda: False)
    assert main_module.main() == 0
    assert gui == [("ui", None)]


def test_frozen_exe_in_terminal_without_arguments_prints_help(monkeypatch, gui, capsys):
    monkeypatch.setattr(sys, "argv", ["Chimera.exe"])
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(entry, "has_console", lambda: True)
    assert main_module.main() == 0
    assert gui == [] and "chimera <команда>" in capsys.readouterr().out


def test_service_run_from_the_scheduled_task_goes_to_the_service(monkeypatch):
    # планировщик зовёт `Chimera.exe service run`: это командная строка, не окно и не UAC
    from modules import service
    got = []
    monkeypatch.setattr(service, "cli", lambda argv: got.append(argv) or 0)
    monkeypatch.setattr(sys, "argv", ["Chimera.exe", "service", "run"])
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(entry, "has_console", lambda: False)
    assert main_module.main() == 0
    assert got == [["run"]]


def test_service_run_is_not_written_to_the_changes_log(monkeypatch, tmp_path):
    from modules import service
    monkeypatch.setattr(commands, "CHANGES_LOG", tmp_path / "changes.log")
    monkeypatch.setattr(service, "cli", lambda argv: 0)
    from modules.cli import app
    app.main(["service", "run"])
    app.main(["service", "status"])
    assert not (tmp_path / "changes.log").exists()
    app.main(["service", "install", "--dry-run"])
    assert (tmp_path / "changes.log").exists()


def test_service_group_is_in_the_table():
    assert "service" in registry.BY_GROUP


# --- автозапуск и обновление зовут окно явно --------------------------------------------------------------------

def test_autostart_task_starts_the_window_in_tray(monkeypatch):
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    command, arguments = autostart._launch_target()
    assert command == sys.executable and arguments == "--window --tray"
    monkeypatch.setattr(paths, "IS_FROZEN", False)
    assert autostart._launch_target()[1].endswith("--window --tray")


def test_old_autostart_task_with_only_tray_is_refreshed(monkeypatch):
    from tests.test_autostart import _Run, _task_query_xml
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    run = _Run(_task_query_xml(sys.executable, "--tray"))
    monkeypatch.setattr(autostart.subprocess, "run", run)
    assert autostart.refresh() is True and run.created
