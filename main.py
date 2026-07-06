"""Точка входа CHIMERA. Режим интерфейса берётся из config.json."""

import ctypes
import sys
from pathlib import Path

from modules import appconfig

ROOT = Path(__file__).parent


def load_config() -> dict:
    return appconfig.load()


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Перезапускает текущий процесс с правами админа через UAC.

    Возвращает True, если запрос на повышение отправлен (текущий процесс
    надо завершить), False — если пользователь отклонил UAC или запуск не на Windows.
    """
    if sys.platform != "win32":
        return False
    if getattr(sys, "frozen", False) or "__compiled__" in globals():  # собранный .exe (PyInstaller/Nuitka)
        program, params = sys.executable, sys.argv[1:]
    else:
        program, params = sys.executable, sys.argv
    args = " ".join(f'"{a}"' for a in params)
    # SW_SHOWNORMAL = 1; rc > 32 — успех
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", program, args, str(ROOT), 1)
    return rc > 32


def main() -> int:
    config = load_config()
    mode = config.get("interface", "ui")

    # UI/TUI работают с hosts и DNS — без прав админа толку нет, повышаемся сразу.
    if mode in ("ui", "tui") and config.get("auto_elevate", True) and not is_admin():
        if relaunch_as_admin():
            return 0  # управление ушло в админский процесс
        print("Не удалось получить права администратора (UAC отклонён). "
              "Применять hosts и менять DNS не выйдет.")

    if mode == "ui":
        from ui.app import run
        run()
        return 0
    if mode == "tui":
        print("TUI-режим пока в разработке. Поставь \"interface\": \"ui\" в config.json.")
        return 1
    if mode == "service":
        print("Service-режим пока в разработке. Поставь \"interface\": \"ui\" в config.json.")
        return 1

    print(f"Неизвестный режим интерфейса: {mode!r}. Доступно: ui, tui, service.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
