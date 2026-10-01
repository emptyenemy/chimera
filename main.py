"""Точка входа CHIMERA. Режим интерфейса берётся из config.json."""

from modules.i18n import t as _tr

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
    from modules.elevation import relaunch
    return relaunch()


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

    from modules.gui_stdio import prepare
    prepare()
    if "--wait-ui-exit" in argv:
        from modules.elevation import wait_for_process
        wait_for_process(int(argv[argv.index("--wait-ui-exit") + 1]))
    config = load_config()
    mode = "ui" if entry.forces_window(argv) or (paths.IS_FROZEN and not argv) else config.get("interface", "ui")

    # Окно уже открыто (или свёрнуто в трей) — показываем его, вторую копию не
    # поднимаем. До UAC: иначе повторный запуск сначала спросил бы права, а потом
    # всё равно вышел. Старт с Windows (--tray) при живой копии просто молча выходит.
    if mode == "ui":
        from modules import instance
        if instance.is_running():
            if "--tray" not in sys.argv:
                instance.signal_existing()
            return 0

    # Старый явный auto_elevate сохраняется; чистая установка открывает окно без UAC.
    # Права для системных действий можно запросить кнопкой в сайдбаре.
    # service — фон от SYSTEM (см. modules/service.py), там UAC неуместен и невозможен.
    if mode == "ui" and config.get("auto_elevate", False) and not is_admin():
        if relaunch_as_admin():
            return 0  # управление ушло в админский процесс
        print(_tr('msg.main.could_not_obtain_administrator_rights_uac_was_de'))

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

    print(_tr('msg.main.unknown_interface_mode_available_ui_tui_service', p0=f'{mode!r}'))
    return 1


def launch() -> int:
    try:
        return main()
    except Exception as error:
        from modules.cli import entry
        if entry.route(sys.argv[1:], frozen=paths.IS_FROZEN, console=entry.has_console()) == "cli":
            raise
        from ui.startup import show_failure
        show_failure(error)
        return 1


if __name__ == "__main__":
    sys.exit(launch())
