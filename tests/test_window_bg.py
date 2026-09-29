"""Фон окна до загрузки страницы — цвет текущей темы, а не синий от старого оформления."""

import re
from pathlib import Path

import pytest

from ui import theme

ROOT = Path(__file__).resolve().parent.parent
OLD_BLUE = "#16161e"


def test_no_old_blue_background_left():
    files = [*ROOT.glob("ui/*.py"), *ROOT.glob("ui/web/**/*.css"), *ROOT.glob("ui/web/**/*.html")]
    hits = [f.name for f in files if OLD_BLUE in f.read_text(encoding="utf-8").lower()]
    assert not hits, f"остался старый синий фон: {hits}"


def test_backends_take_background_from_theme():
    """Цвет берётся из ui.theme, а не зашит в бэкенде — иначе движки разъедутся."""
    for name in ("backend_qt.py", "backend_webview.py"):
        src = (ROOT / "ui" / name).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}", src), f"{name}: зашит цвет"
        assert "window_bg(" in src, f"{name}: не берёт фон из ui.theme"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_window_bg_matches_table(mode):
    assert theme.window_bg(mode) == theme.WINDOW_BG[mode]
    assert re.fullmatch(r"#[0-9a-f]{6}", theme.window_bg(mode))


def test_window_bg_values():
    assert theme.window_bg("dark") == "#0a0a0a"  # --background тёмной темы, oklch(0.145 0 0)
    assert theme.window_bg("light") == "#ffffff"


def test_window_bg_follows_config(monkeypatch):
    from modules import appconfig
    monkeypatch.setattr(appconfig, "load", lambda: {"theme": "light"})
    assert theme.window_bg() == "#ffffff"
    monkeypatch.setattr(appconfig, "load", lambda: {"theme": "dark"})
    assert theme.window_bg() == "#0a0a0a"
