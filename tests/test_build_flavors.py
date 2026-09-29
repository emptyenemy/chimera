import json
from types import SimpleNamespace

import pytest

from modules import selfupdate, version
from ui import tray_model
from ui.tray_win32 import Tray, close_to_tray


@pytest.mark.parametrize("flavor,suffix,backend", [("qt", "", "pyside6"), ("webview", "-webview", "pywebview"), ("lite", "-lite", "browser")])
def test_flavor_names_and_backends(flavor, suffix, backend):
    assert version.asset_suffix(flavor) == suffix
    assert version.default_backend(flavor) == backend


@pytest.mark.parametrize("flavor", version.FLAVORS)
def test_updater_selects_only_its_flavor(monkeypatch, flavor):
    import re
    monkeypatch.setattr(selfupdate, "ASSET_RE", re.compile(r"^Chimera-.+-win64" + re.escape(version.asset_suffix(flavor)) + r"\.zip$"))
    release = {"tag_name": "v0.5.0", "assets": [{"name": f"Chimera-0.5.0-win64{version.asset_suffix(f)}.zip"} for f in version.FLAVORS]}
    assert selfupdate._zip_asset(release)["name"] == f"Chimera-0.5.0-win64{version.asset_suffix(flavor)}.zip"


def test_webview_tray_uses_shared_commands(monkeypatch):
    from modules import appconfig
    calls = []
    tray = Tray.__new__(Tray)
    tray.api = SimpleNamespace(
        hub=SimpleNamespace(snapshot=lambda: {"proxy": {"running": True}}),
        dispatch=lambda method, args: calls.append((method, json.loads(args))) or json.dumps({"ok": True, "data": {"steps": []}}))
    tray.show = lambda: calls.append("show")
    tray.quit_app = lambda: calls.append("quit")
    entries = tray.menu_entries()
    assert next(checked for command, _, checked in entries if command == 11)
    tray.command(11)
    tray.command(20)
    assert calls == [("proxy_stop", []), tray_model.PANIC_COMMAND]
    tray.available = False
    monkeypatch.setattr(appconfig, "load", lambda: {"close_to_tray": True})
    assert not close_to_tray(tray)


def test_missing_webview_runtime_falls_back_before_creating_window(monkeypatch):
    from ui import app, webview_runtime
    from modules import appconfig, paths
    calls = []
    monkeypatch.setattr(appconfig, "load", lambda: {"ui_backend": "pywebview"})
    monkeypatch.setattr(paths, "IS_FROZEN", False)
    monkeypatch.setattr(webview_runtime, "installed", lambda: False)
    monkeypatch.setattr(app, "_load", lambda name: SimpleNamespace(run=lambda: calls.append(name)))
    app.run()
    assert calls == ["browser"]
