"""Запуск TUI: полноэкранный (Textual) или простое меню цифрами (`chimera tui --simple`).

Полноэкранный интерфейс — клиент работающей Chimera (tui/textual_app.py). Он нужен настоящий
терминал; если его нет (вывод в файл, конвейер) или Textual не импортируется, печатается
причина и запускается старое меню (tui/app.py), которое поведения не меняло.
"""

import sys


def _say(text: str) -> None:
    print(text, file=sys.stderr)


def run_simple() -> int:
    """Старое меню цифрами: работает через собственный Api, без Textual."""
    from tui.app import run
    return run()


def _interactive() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def run(simple: bool = False, *, interactive=None, remote=None) -> int:
    if simple:
        return run_simple()
    if not (interactive() if interactive else _interactive()):
        _say("Полноэкранному интерфейсу нужен интерактивный терминал. Запускаю простое меню (chimera tui --simple).")
        return run_simple()
    try:
        from tui.remote import Remote
        from tui.textual_app import ChimeraTui
    except ImportError as e:
        _say(f"Не удалось загрузить Textual ({e}). Запускаю простое меню (chimera tui --simple).")
        return run_simple()
    try:
        ChimeraTui(remote or Remote()).run()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001 — терминал не потянул интерфейс: откатываемся на простое меню
        _say(f"Полноэкранный интерфейс не запустился ({type(e).__name__}: {e}). Запускаю простое меню (chimera tui --simple).")
        return run_simple()
    return 0
