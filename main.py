"""Точка входа CHIMERA. Режим интерфейса берётся из config.json."""

import ctypes
import os
import sys
import threading
from pathlib import Path

from modules import appconfig, paths

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
    # Командная строка — путь по умолчанию: `chimera status`, `chimera service run` и так далее
    # (modules/cli). Окно открывают --window/--browser, автозапуск (--tray), а также двойной
    # клик по exe без аргументов и без консоли (modules/cli/entry.py). Права администратора
    # для команд не запрашиваем: они говорят с уже работающей Chimera по каналу управления.
    from modules.cli import entry
    argv = sys.argv[1:]
    if entry.route(argv, frozen=paths.IS_FROZEN, console=entry.has_console()) == "cli":
        from modules.cli.app import main as cli_main
        return cli_main(argv)

    config = load_config()
    mode = "ui" if entry.forces_window(argv) else config.get("interface", "ui")

    # Окно уже открыто (или свёрнуто в трей) — показываем его, вторую копию не
    # поднимаем. До UAC: иначе повторный запуск сначала спросил бы права, а потом
    # всё равно вышел. Старт с Windows (--tray) при живой копии просто молча выходит.
    if mode == "ui":
        from modules import instance
        if instance.is_running():
            if "--tray" not in sys.argv:
                instance.signal_existing()
            return 0

    # Окно работает с hosts и DNS — без прав админа толку нет, повышаемся сразу. TUI — клиент
    # работающей Chimera (tui/remote.py), права нужны ей, а не терминалу.
    # service — фон от SYSTEM (см. modules/service.py), там UAC неуместен и невозможен.
    if mode == "ui" and config.get("auto_elevate", True) and not is_admin():
        if relaunch_as_admin():
            return 0  # управление ушло в админский процесс
        print("Не удалось получить права администратора (UAC отклонён). "
              "Применять hosts и менять DNS не выйдет.")

    if mode == "ui":
        from ui.app import run
        run(entry.backend_override(argv))
        # Окно закрыто, процессы погашены (Api.shutdown). Интерпретатор на выходе
        # ждёт пулы потоков, а там может дорабатывать сетевой таймаут фоновой
        # проверки — закрытая программа не должна висеть в памяти ради этого.
        guard = threading.Timer(5.0, os._exit, args=(0,))
        guard.daemon = True
        guard.start()
        return 0
    if mode == "tui":
        from tui.launch import run
        return run()
    if mode == "service":
        # запуск без аргументов с interface=service в конфиге — тот же фоновый
        # процесс, что и `service run`; сама задача автозапуска ставится отдельно
        # командой `python main.py service install`.
        from modules import service
        return service.run()

    print(f"Неизвестный режим интерфейса: {mode!r}. Доступно: ui, tui, service.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
