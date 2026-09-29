"""Тема окна: разбор системной, таблица фонов, валидация настройки theme."""

import sys
import types

import pytest

from modules import appconfig
from ui import theme


def _fake_winreg(monkeypatch, value=None, error=None):
    """Подменяет winreg: AppsUseLightTheme = value либо ошибка чтения."""
    mod = types.ModuleType("winreg")
    mod.HKEY_CURRENT_USER = 1

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def open_key(root, path):
        if error:
            raise error
        assert path == theme.PERSONALIZE_KEY
        return _Key()

    def query(key, name):
        assert name == "AppsUseLightTheme"
        return value, 4

    mod.OpenKey, mod.QueryValueEx = open_key, query
    monkeypatch.setitem(sys.modules, "winreg", mod)


def test_explicit_theme_ignores_system(monkeypatch):
    _fake_winreg(monkeypatch, 1)
    assert theme.resolve_theme("dark") == "dark"
    _fake_winreg(monkeypatch, 0)
    assert theme.resolve_theme("light") == "light"


def test_system_reads_registry(monkeypatch):
    _fake_winreg(monkeypatch, 1)
    assert theme.resolve_theme("system") == "light"
    _fake_winreg(monkeypatch, 0)
    assert theme.resolve_theme("system") == "dark"


def test_system_falls_back_to_dark_on_error(monkeypatch):
    _fake_winreg(monkeypatch, error=OSError("нет ключа"))
    assert theme.resolve_theme("system") == "dark"


def test_system_dark_without_winreg(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", None)  # import winreg -> ImportError
    assert theme.resolve_theme("system") == "dark"


def test_resolve_theme_reads_config_by_default(monkeypatch):
    monkeypatch.setattr(appconfig, "load", lambda: {"theme": "light"})
    assert theme.resolve_theme() == "light"


def test_unknown_stored_theme_is_treated_as_system(monkeypatch):
    _fake_winreg(monkeypatch, 1)
    assert theme.resolve_theme("neon") == "light"


def test_window_bg_table():
    assert theme.WINDOW_BG == {"dark": "#0a0a0a", "light": "#ffffff"}
    assert theme.window_bg("dark") == "#0a0a0a"
    assert theme.window_bg("light") == "#ffffff"


def test_boot_script_sets_attribute_and_class():
    dark = theme.boot_script("dark")
    assert 'setAttribute("data-theme","dark")' in dark and 'classList.add("dark")' in dark
    light = theme.boot_script("light")
    assert 'setAttribute("data-theme","light")' in light and 'classList.remove("dark")' in light


def test_theme_default_is_system():
    assert appconfig.DEFAULTS["theme"] == "system"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(appconfig, "CONFIG_PATH", tmp_path / "config.json")


@pytest.mark.parametrize("value", ["system", "light", "dark"])
def test_set_theme_accepts_known(cfg, value):
    assert appconfig.set_value("theme", value)["theme"] == value


@pytest.mark.parametrize("value", ["neon", "", None, 1, "Dark"])
def test_set_theme_rejects_unknown(cfg, value):
    with pytest.raises(ValueError, match="system, light, dark"):
        appconfig.set_value("theme", value)
    assert appconfig.load()["theme"] == "system"


def test_api_config_set_rejects_with_clear_error(cfg):
    from ui.api import Api
    res = Api.config_set(object.__new__(Api), "theme", "neon")
    assert res["ok"] is False and "system, light, dark" in res["error"]


def test_theme_is_writable_from_cli():
    from modules import control
    assert "theme" in control.CONFIG_KEYS_WRITABLE


def test_browser_page_gets_theme_before_first_paint():
    from ui import backend_browser
    page = backend_browser._mark_page(b"<html><head></head><body></body></html>", "tok", "light")
    assert b'data-theme' in page and page.index(b"data-theme") < page.index(b"</head>")
    assert b'classList.remove("dark")' in page
