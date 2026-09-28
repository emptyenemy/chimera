"""Трей и крестик окна — на Qt без экрана (offscreen): ничего не показывается."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtGui = pytest.importorskip("PySide6.QtGui")

from ui import backend_qt  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Hub:
    def __init__(self, states):
        self.states = states

    def snapshot(self):
        return self.states


class _Api:
    def __init__(self, states, result=None):
        self.hub = _Hub(states)
        self.result = result or {"ok": True, "data": None}
        self.calls = []

    def dispatch(self, method, args_json):
        self.calls.append((method, json.loads(args_json)))
        return json.dumps(self.result)


class _Pool:
    """Выполняет сразу, в том же потоке — тесту не надо ждать."""

    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args):
        self.submitted.append(args)
        fn(*args)


class _Bridge:
    def __init__(self):
        self.pool = _Pool()


@pytest.fixture
def config(monkeypatch):
    cfg = {"close_to_tray": True}
    monkeypatch.setattr(backend_qt.appconfig, "load", lambda: dict(cfg))
    monkeypatch.setattr(backend_qt.appconfig, "set_value", lambda k, v: cfg.__setitem__(k, v) or dict(cfg))
    return cfg


def _tray(app, states, result=None):
    window = backend_qt.MainWindow()
    api = _Api(states, result)
    tray = backend_qt.Tray(app, window, api, _Bridge())
    window.tray = tray
    return window, api, tray


def test_menu_reflects_module_states(app, config):
    _, _, tray = _tray(app, {"winws": {"running": True}, "hosts": {"applied": True}})
    assert tray.status.text() == "Защита активна · 2 из 4"
    assert tray.toggles["winws"].isChecked()
    assert tray.toggles["hosts"].isChecked()
    assert not tray.toggles["proxy"].isChecked()
    assert tray.icon.toolTip() == "Chimera — защита активна · 2 из 4"


def test_toggle_runs_same_command_as_dashboard(app, config):
    _, api, tray = _tray(app, {"winws": {"running": False, "last_strategy": "alt2", "strategies": [{"id": "x"}]}})
    tray.toggle("winws", True)
    assert api.calls == [("winws_start", ["alt2"])]
    assert "winws" not in tray.busy  # команда закончилась — пункт снова доступен


def test_toggle_error_is_reported(app, config):
    _, _, tray = _tray(app, {}, result={"ok": False, "error": "Нужны права администратора"})
    got = []
    tray.notified.connect(lambda title, text: got.append((title, text)))
    tray.toggle("proxy", True)
    assert got == [("Прокси: не получилось", "Нужны права администратора")]


def test_close_hides_to_tray_and_hints_once(app, config, monkeypatch):
    window, _, tray = _tray(app, {})
    quits = []
    monkeypatch.setattr(backend_qt.QApplication, "quit", lambda: quits.append(1))
    messages = []
    monkeypatch.setattr(tray.icon, "showMessage", lambda *a: messages.append(a[0]))
    window.show()
    window.close()
    assert not window.isVisible()
    assert quits == []  # программа живёт дальше
    assert messages == ["Chimera работает в трее"]
    window.show()
    window.close()
    assert messages == ["Chimera работает в трее"]  # подсказка — только в первый раз


def test_close_quits_when_tray_disabled_in_settings(app, config, monkeypatch):
    config["close_to_tray"] = False
    window, _, _ = _tray(app, {})
    quits = []
    monkeypatch.setattr(backend_qt.QApplication, "quit", lambda: quits.append(1))
    window.show()
    window.close()
    assert quits == [1]


def test_quit_request_closes_program_and_hides_tray_icon(app, config, monkeypatch):
    # обновление просит выйти из потока пула — сигнал доводит это до потока UI
    window, _, tray = _tray(app, {})
    quits = []
    monkeypatch.setattr(backend_qt.QApplication, "quit", lambda: quits.append(1))
    window.quit_requested.emit()
    assert quits == [1]
    assert not tray.icon.isVisible()


def test_close_quits_without_tray(app, config, monkeypatch):
    window = backend_qt.MainWindow()  # трей не поднялся (нет области уведомлений)
    quits = []
    monkeypatch.setattr(backend_qt.QApplication, "quit", lambda: quits.append(1))
    window.show()
    window.close()
    assert quits == [1]
