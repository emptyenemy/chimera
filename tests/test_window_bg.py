"""Фон окна до загрузки страницы — цвет текущей темы, а не синий от старого оформления."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_BLUE = "#16161e"


def test_no_old_blue_background_left():
    files = [*ROOT.glob("ui/*.py"), *ROOT.glob("ui/web/**/*.css"), *ROOT.glob("ui/web/**/*.html")]
    hits = [f.name for f in files if OLD_BLUE in f.read_text(encoding="utf-8").lower()]
    assert not hits, f"остался старый синий фон: {hits}"


def test_qt_and_webview_use_same_background():
    qt = (ROOT / "ui" / "backend_qt.py").read_text(encoding="utf-8")
    webview = (ROOT / "ui" / "backend_webview.py").read_text(encoding="utf-8")
    qt_bg = re.search(r'WINDOW_BG = "(#[0-9a-f]{6})"', qt).group(1)
    webview_bg = re.search(r'background_color="(#[0-9a-f]{6})"', webview).group(1)
    assert qt_bg == webview_bg == "#0a0a0a"  # --background темы, oklch(0.145 0 0)
