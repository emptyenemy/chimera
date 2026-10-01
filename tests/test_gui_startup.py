import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from modules import appconfig, elevation, paths
from modules.cli import entry
from ui import app, startup, webview_runtime


@pytest.mark.parametrize("interface", ["service", "tui", "ui"])
def test_double_click_opens_gui_even_with_legacy_background_mode(monkeypatch, interface):
    monkeypatch.setattr(sys, "argv", ["Chimera.exe"])
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(entry, "has_console", lambda: False)
    monkeypatch.setattr(main, "load_config", lambda: {"interface": interface, "auto_elevate": False})
    from modules import instance
    monkeypatch.setattr(instance, "is_running", lambda: False)
    monkeypatch.setattr(main.threading, "Timer", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))
    run = Mock()
    monkeypatch.setattr(app, "run", run)
    assert main.main() == 0
    run.assert_called_once_with(None)


def test_clean_defaults_open_ui_without_uac(tmp_path, monkeypatch):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")
    assert appconfig.load()["interface"] == "ui"
    assert appconfig.load()["auto_elevate"] is False


@pytest.mark.parametrize("stored", [[], 42, "broken", None])
def test_invalid_config_shape_does_not_break_startup(tmp_path, monkeypatch, stored):
    file = tmp_path / "config.json"
    file.write_text(json.dumps(stored), encoding="utf-8")
    monkeypatch.setattr(appconfig, "CONFIG_PATH", file)
    assert appconfig.load()["interface"] == "ui"
    assert json.loads(file.read_text(encoding="utf-8")) == stored


@pytest.mark.parametrize("result", [42, 5, 0])
def test_uac_relaunch_uses_gui_flag_and_preserves_quoted_arguments(monkeypatch, result):
    shell = Mock(return_value=result)
    monkeypatch.setattr(sys, "argv", [r"C:\Программа с пробелами\Chimera.exe"])
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(elevation.ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(ShellExecuteW=shell)))
    assert elevation.relaunch() is (result > 32)
    assert shell.call_args.args[3] == "--window"
    elevation.relaunch(["--browser", "--wait-ui-exit", "123"])
    assert shell.call_args.args[3] == "--browser --wait-ui-exit 123"


def test_native_engine_failure_falls_back_to_browser(monkeypatch):
    monkeypatch.setattr(appconfig, "load", lambda: {"ui_backend": "pywebview"})
    monkeypatch.setattr(paths, "IS_FROZEN", False)
    monkeypatch.setattr(webview_runtime, "bundled", lambda: None)
    monkeypatch.setattr(webview_runtime, "installed", lambda: True)
    monkeypatch.setattr(startup, "log_failure", Mock())
    native = Mock(side_effect=RuntimeError("native failed"))
    browser = Mock()
    monkeypatch.setattr(app, "_load", lambda name: SimpleNamespace(run=native if name == "pywebview" else browser))
    app.run()
    native.assert_called_once()
    browser.assert_called_once()


def test_missing_system_runtime_uses_bundled_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(appconfig, "load", lambda: {"ui_backend": "pywebview"})
    monkeypatch.setattr(paths, "IS_FROZEN", False)
    monkeypatch.setattr(webview_runtime, "bundled", lambda: tmp_path)
    monkeypatch.setattr(webview_runtime, "installed", lambda: pytest.fail("system runtime should not be queried"))
    native = Mock()
    monkeypatch.setattr(app, "_load", lambda name: SimpleNamespace(run=native))
    app.run()
    native.assert_called_once()


def test_fatal_gui_exception_opens_native_error_window(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["Chimera.exe"])
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(entry, "has_console", lambda: False)
    monkeypatch.setattr(main, "main", Mock(side_effect=OSError("broken engine")))
    show = Mock()
    monkeypatch.setattr(startup, "show_failure", show)
    assert main.launch() == 1
    show.assert_called_once()


def test_startup_log_contains_stack_but_not_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    try:
        raise RuntimeError("private://secret-token")
    except RuntimeError as error:
        logfile = startup.log_failure("engine", error)
    text = logfile.read_text(encoding="utf-8")
    assert "RuntimeError" in text and "test_gui_startup.py" in text
    assert "secret-token" not in text


def test_cancelling_elevation_keeps_the_current_window(monkeypatch):
    from ui.api import Api
    api = Api.__new__(Api)
    api.request_quit = Mock()
    monkeypatch.setattr(elevation, "relaunch", Mock(return_value=False))
    assert api.app_elevate() == {"ok": True, "data": {"started": False}}
    api.request_quit.assert_not_called()


def test_lite_without_browser_uses_portable_native_window(monkeypatch, tmp_path):
    from modules import version
    monkeypatch.setattr(paths, "IS_FROZEN", True)
    monkeypatch.setattr(version, "FLAVOR", "lite")
    monkeypatch.setattr(appconfig, "load", lambda: {"ui_backend": "browser"})
    monkeypatch.setattr(webview_runtime, "bundled", lambda: tmp_path)
    monkeypatch.setattr(startup, "log_failure", Mock())
    calls = []

    def launch(name):
        calls.append(name)
        if name == "browser":
            raise OSError("browser unavailable")

    monkeypatch.setattr(app, "_load", lambda name: SimpleNamespace(run=lambda: launch(name)))
    app.run()
    assert calls == ["browser", "pywebview"]


def test_browser_bind_failure_cleans_api_before_engine_fallback(monkeypatch):
    from modules import control
    from ui import backend_browser
    api = SimpleNamespace(push=None, shutdown=Mock())
    monkeypatch.setattr(backend_browser, "Api", lambda: api)
    monkeypatch.setattr(control, "start_for", Mock())
    monkeypatch.setattr(backend_browser, "ThreadingHTTPServer", Mock(side_effect=OSError("port busy")))
    with pytest.raises(OSError, match="port busy"):
        backend_browser.run()
    api.shutdown.assert_called_once()
