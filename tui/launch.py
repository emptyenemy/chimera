"""Запуск TUI: полноэкранный (Textual) или простое меню цифрами (`chimera tui --simple`).

Полноэкранный интерфейс — клиент работающей Chimera (tui/textual_app.py). Он нужен настоящий
терминал; если его нет (вывод в файл, конвейер) или Textual не импортируется, печатается
причина и запускается старое меню (tui/app.py), которое поведения не меняло.
"""

from modules.i18n import t as _tr

import os
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
    if os.environ.get("CHIMERA_TUI_PROBE") == "1":
        from tui.build_probe import run as probe
        return probe()
    if simple:
        return run_simple()
    if not (interactive() if interactive else _interactive()):
        _say(_tr('tui.launch.the_full_screen_interface_needs_an_interactive_t'))
        return run_simple()
    try:
        from tui.remote import Remote
        from tui.textual_app import ChimeraTui
    except ImportError as e:
        _say(_tr('tui.launch.could_not_load_textual_starting_the_simple_menu', p0=e))
        return run_simple()
    try:
        ChimeraTui(remote or Remote()).run()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001 — терминал не потянул интерфейс: откатываемся на простое меню
        _say(_tr('tui.launch.the_full_screen_interface_could_not_start_starti', p0=type(e).__name__, p1=e))
        return run_simple()
    return 0
