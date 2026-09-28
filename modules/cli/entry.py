"""Куда идёт запуск: в командную строку или в окно. Решает main.py.

`chimera` по умолчанию командная строка. Окно открывают флаги --window и --browser (и
служебный --tray от автозапуска). Исключение — запуск собранного exe без аргументов и без
консоли-родителя (двойной клик, ярлык): открывается окно, как раньше. Из терминала без
аргументов печатается справка. Из исходников (`python main.py`) окно открывается всегда,
как и было: разработчику справка по запуску не нужна.
"""

import ctypes
import sys

WINDOW_FLAGS = ("--window", "--browser", "--tray")


def has_console() -> bool:
    """Есть ли у процесса консоль (собранный exe в режиме attach получает консоль родителя)."""
    if sys.platform != "win32":
        return sys.stdout is not None and sys.stdout.isatty()
    try:
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except (OSError, AttributeError):
        return False


def route(argv: list[str], frozen: bool, console: bool) -> str:
    """'cli' или 'gui' для этого запуска."""
    if any(a in WINDOW_FLAGS for a in argv):
        return "gui"
    if not argv:
        return "cli" if (frozen and console) else "gui"
    return "cli"


def forces_window(argv: list[str]) -> bool:
    """--window и --browser открывают окно, даже если в config.json указан другой режим."""
    return "--window" in argv or "--browser" in argv


def backend_override(argv: list[str]) -> str | None:
    return "browser" if "--browser" in argv else None
