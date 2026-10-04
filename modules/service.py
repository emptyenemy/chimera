"""Service-режим: фоновый процесс без окна, поднимает автозапуски и держит их.

«Служба» реализована так же, как автозапуск GUI (modules/autostart.py) — задачей
в Планировщике заданий, но с триггером на старт системы и принципалом SYSTEM
(наивысшие права, без интерактивного пользователя и без UAC). Отдельной службы
Windows (SCM) нет сознательно — не тащить pywin32 ради этого одного момента.

Управление процессом:
  - "запущен ли фон" — именованный мьютекс MUTEX_RUNNING в Global\\-пространстве:
    run() создаёт его на старте и держит открытым всё время жизни процесса,
    ОС сама снимает мьютекс, если процесс упал — надёжнее pid-файла, который
    может протухнуть (pid переиспользован другим процессом).
  - "гасись" — именованное событие EVENT_STOP (тоже Global\\): run() ждёт его
    в цикле, `service stop` открывает и взводит (SetEvent) из другого процесса.
  - pid-файл (data/service.pid) — только для отображения в status(), не источник
    истины о том, жив ли процесс.

Общая с UI логика автозапуска — autostart_modules(): раньше жила только в
Api._autostart_all, теперь общая, чтобы UI и сервис не расходились в поведении.
Нюанс: прокси в режиме PAC пишет системный прокси в HKCU текущего пользователя —
под SYSTEM это чужой (и фактически ничей) куст, поэтому под сервисом PAC
пропускаем с записью в лог, поднимаем только TUN (см. allow_proxy_pac).
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraRuntimeError

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from modules import paths
from modules.fileutil import atomic_write_text
from modules.hosts.manager import is_admin

ROOT = Path(__file__).parent.parent
MAIN_PY = ROOT / "main.py"
TASK_NAME = "CHIMERA-Service"

PID_PATH = paths.data_path("service.pid")
LOG_PATH = paths.log_path("service.log")

# Global\ — видно из любой сессии (служба поднимается в сессии 0, `service stop`
# зовут из пользовательской сессии). Создание/открытие объекта в этом
# пространстве имён требует SeCreateGlobalPrivilege — есть у SYSTEM и у
# администраторов по умолчанию, так что обеим сторонам достаточно прав.
MUTEX_RUNNING = r"Global\CHIMERA_Service_Running"
EVENT_STOP = r"Global\CHIMERA_Service_Stop"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ERROR_ALREADY_EXISTS = 183

kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

_SYNCHRONIZE = 0x00100000
_EVENT_MODIFY_STATE = 0x0002


def is_supported() -> bool:
    return sys.platform == "win32"


# --- именованные объекты синхронизации (обёртки — чтобы легко подменять в тестах) --

def _create_mutex(name: str):
    return kernel32.CreateMutexW(None, False, name)


def _open_mutex(name: str):
    h = kernel32.OpenMutexW(_SYNCHRONIZE, False, name)
    return h or None


def _create_event(name: str):
    return kernel32.CreateEventW(None, True, False, name)  # manual-reset, не взведено


def _open_event(name: str):
    h = kernel32.OpenEventW(_SYNCHRONIZE | _EVENT_MODIFY_STATE, False, name)
    return h or None


def _set_event(handle) -> None:
    kernel32.SetEvent(handle)


def _wait_event(handle, timeout_ms: int) -> int:
    return kernel32.WaitForSingleObject(handle, timeout_ms)


def _close_handle(handle) -> None:
    if handle:
        kernel32.CloseHandle(handle)


def is_running() -> bool:
    """Жив ли фоновый процесс службы ПРЯМО СЕЙЧАС (мьютекс — источник истины,
    не pid-файл: тот может остаться от процесса, который уже умер)."""
    if not is_supported():
        return False
    h = _open_mutex(MUTEX_RUNNING)
    if not h:
        return False
    _close_handle(h)
    return True


def send_stop() -> bool:
    """Сигналит запущенному процессу службы остановиться. True — сигнал реально
    доставлен (процесс был жив), False — служба и так не запущена."""
    if not is_running():
        return False
    h = _open_event(EVENT_STOP)
    if not h:
        return False
    try:
        _set_event(h)
    finally:
        _close_handle(h)
    return True


# --- pid-файл (только для status(), не для проверки живости) ------------------

def _write_pid() -> None:
    atomic_write_text(PID_PATH, str(os.getpid()))   # окно читает PID постоянно — без полфайла


def _read_pid() -> int | None:
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _remove_pid() -> None:
    try:
        PID_PATH.unlink()
    except OSError:
        pass


# --- задача планировщика -------------------------------------------------------

def _launch_target() -> tuple[str, str]:
    """(команда, аргументы) для действия задачи — тот же процесс, что и
    `python main.py service run`, но с фиксированными аргументами."""
    if paths.IS_FROZEN:
        return sys.executable, "service run"
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")  # без консольного окна
    command = str(pyw if pyw.exists() else exe)
    return command, f'"{MAIN_PY}" service run'


def _task_xml() -> str:
    command, arguments = _launch_target()
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Description>Фоновая служба CHIMERA — автозапуск отмеченных модулей "
        "при старте системы, без окна</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <BootTrigger>\n"
        "      <Enabled>true</Enabled>\n"
        "    </BootTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <UserId>S-1-5-18</UserId>\n"  # well-known SID SYSTEM — без опоры на локаль
        "      <LogonType>ServiceAccount</LogonType>\n"
        "      <RunLevel>HighestAvailable</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{escape(command)}</Command>\n"
        f"      <Arguments>{escape(arguments)}</Arguments>\n"
        f"      <WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def is_installed() -> bool:
    if not is_supported():
        return False
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, creationflags=_NO_WINDOW,
    )
    return r.returncode == 0


def install(dry_run: bool = False) -> dict:
    xml = _task_xml()
    if dry_run:
        print(xml)
        return {"dry_run": True, "xml": xml}
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        Path(path).write_text(xml, encoding="utf-16")
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or _tr('msg.modules.service.schtasks_create_failed')).strip())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"installed": True}


def uninstall(dry_run: bool = False) -> dict:
    command = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    if dry_run:
        printed = " ".join(command)
        print(printed)
        return {"dry_run": True, "command": printed}
    r = subprocess.run(command, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if r.returncode != 0 and is_installed():
        raise RuntimeError((r.stderr or r.stdout or _tr('msg.modules.service.schtasks_delete_failed')).strip())
    return {"installed": is_installed()}


def start_task() -> dict:
    """Запускает установленную задачу немедленно, не дожидаясь перезагрузки."""
    if not is_installed():
        raise ChimeraRuntimeError('err.service.the_service_is_not_installed_run_service_install')
    r = subprocess.run(
        ["schtasks", "/Run", "/TN", TASK_NAME],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or _tr('msg.modules.service.schtasks_run_failed')).strip())
    return {"started": True}


def stop_task() -> dict:
    """Сигналит фоновому процессу остановиться. Саму задачу планировщика не трогает —
    она снова поднимет процесс на следующей загрузке системы, это ожидаемо."""
    return {"signaled": send_stop()}


def status() -> dict:
    running = is_running()
    return {
        "installed": is_installed(),
        "running": running,
        "pid": _read_pid() if running else None,
    }


# --- общая логика автозапуска (UI и сервис) ------------------------------------

def autostart_modules(tg, winws, proxy, log=lambda msg: None, allow_proxy_pac: bool = True) -> None:
    """Поднимает то, что помечено автозапуском — общая точка входа для
    Api._autostart_all (UI) и service.run(). Ошибки одного модуля не мешают
    остальным и не бросаются наверх — UI узнаёт о них через *_state, сервис
    пишет в свой лог через log().
    """
    if tg.config.get("autostart"):
        try:
            tg.start()
        except Exception as e:
            log(f"tg: автозапуск не удался — {e}")
    if winws.config.get("autostart"):
        if is_admin():
            try:
                winws.autostart()
            except Exception as e:
                log(f"winws: автозапуск не удался — {e}")
        else:
            log("winws: автозапуск пропущен — нужны права администратора")
    if proxy.config.get("autostart"):
        if proxy.config.get("mode", "pac") == "pac" and not allow_proxy_pac:
            log("proxy: автозапуск в режиме PAC пропущен под сервисом — "
                "PAC пишет системный прокси в HKCU текущего пользователя, "
                "под SYSTEM это чужой куст. Переключи на TUN или подними прокси из UI.")
        else:
            try:
                proxy.start()
            except Exception as e:
                log(f"proxy: автозапуск не удался — {e}")


def start_lists_watch(winws, proxy, hosts, stop, log):
    """Следит за lists/*.txt: правка файла напрямую (агентом, вручную) применяется к модулям
    службы так же, как lists_save в окне (modules/filewatch.py). Останавливается по `stop`."""
    from modules import filewatch, liveapply

    watcher = filewatch.ListsWatcher(
        lambda kind, name: liveapply.apply_event(kind, name, winws, proxy, hosts), log=log)
    watcher.start_background(stop)
    return watcher


# --- фоновый процесс (`service run`) -------------------------------------------

def run() -> int:
    """Тело фонового процесса: поднимает автозапуски, ждёт сигнала остановки,
    корректно всё гасит. Именно это выполняет задача планировщика при старте
    системы (см. _launch_target) — но команду можно вызвать и руками для теста."""
    import logging

    logger = logging.getLogger("chimera-service")
    logger.setLevel(logging.INFO)
    # служба живёт неделями: лог ограничен по размеру (1 МБ и два прежних файла)
    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)

    if not is_supported():
        logger.error("service-режим поддерживается только на Windows")
        logger.removeHandler(handler)
        handler.close()
        return 1

    running_mutex = _create_mutex(MUTEX_RUNNING)
    if not running_mutex or ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        logger.error("служба уже запущена (мьютекс %s занят)", MUTEX_RUNNING)
        _close_handle(running_mutex)
        logger.removeHandler(handler)
        handler.close()
        return 1
    stop_event, api, previous_handler = None, None, None
    import signal

    interrupted = {"flag": False}

    def _on_sigint(signum, frame):
        interrupted["flag"] = True

    try:
        from modules import control
        from ui.api import Api
        stop_event = _create_event(EVENT_STOP)
        if not stop_event:
            raise ctypes.WinError(ctypes.get_last_error())
        _write_pid()
        logger.info("служба запущена, pid=%s", os.getpid())
        api = Api(service_owned=True)
        api.request_quit = lambda: interrupted.update(flag=True)
        if api._trial.active is None:
            autostart_modules(api.tg, api.winws, api.proxy, log=logger.info, allow_proxy_pac=False)
        control.start_for(api)
        try:
            previous_handler = signal.signal(signal.SIGINT, _on_sigint)
        except (ValueError, OSError):
            pass
        logger.info("ожидание сигнала остановки")
        while not interrupted["flag"]:
            if _wait_event(stop_event, 1000) == 0:
                break
            control.refresh_service_access()
    finally:
        try:
            if api is not None:
                api.shutdown()
        finally:
            _remove_pid()
            _close_handle(stop_event)
            _close_handle(running_mutex)
            if previous_handler is not None:
                signal.signal(signal.SIGINT, previous_handler)
            logger.info("служба остановлена")
            logger.removeHandler(handler)
            handler.close()

    return 0


# --- CLI (`python main.py service ...`) ----------------------------------------

def cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="main.py service", add_help=True)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_install = sub.add_parser("install", help=_tr('msg.modules.service.install_the_service_startup_task'))
    p_install.add_argument("--dry-run", action="store_true", help=_tr('msg.modules.service.print_task_xml_only'))
    p_uninstall = sub.add_parser("uninstall", help=_tr('msg.modules.service.remove_the_service_startup_task'))
    p_uninstall.add_argument("--dry-run", action="store_true", help=_tr('msg.modules.service.print_the_command_only'))
    sub.add_parser("start", help=_tr('msg.modules.service.start_the_task_immediately'))
    sub.add_parser("stop", help=_tr('msg.modules.service.signal_the_running_service_to_stop'))
    sub.add_parser("status", help=_tr('msg.modules.service.show_whether_the_task_is_installed_and_the_servi'))
    sub.add_parser("run", help=_tr('msg.modules.service.run_the_background_service_called_by_task_schedu'))
    ns = parser.parse_args(argv)

    if not is_supported():
        print(_tr('msg.modules.service.service_mode_is_supported_only_on_windows'))
        return 1

    if ns.cmd == "install":
        try:
            install(dry_run=ns.dry_run)
        except Exception as e:
            print(_tr('msg.modules.service.could_not_install_the_task', p0=f'{e}'))
            return 1
        if not ns.dry_run:
            print(_tr('msg.modules.service.service_startup_task_installed'))
        return 0

    if ns.cmd == "uninstall":
        try:
            uninstall(dry_run=ns.dry_run)
        except Exception as e:
            print(_tr('msg.modules.service.could_not_remove_the_task', p0=f'{e}'))
            return 1
        if not ns.dry_run:
            print(_tr('msg.modules.service.service_startup_task_removed'))
        return 0

    if ns.cmd == "start":
        try:
            start_task()
        except Exception as e:
            print(_tr('msg.modules.service.could_not_start_the_service', p0=f'{e}'))
            return 1
        print(_tr('msg.modules.service.service_started'))
        return 0

    if ns.cmd == "stop":
        res = stop_task()
        print(_tr('msg.modules.service.stop_signal_sent') if res["signaled"] else _tr('msg.modules.service.service_is_not_running'))
        return 0

    if ns.cmd == "status":
        st = status()
        print(_tr('msg.modules.service.task_installed', p0=f"{(_tr('msg.modules.service.yes') if st['installed'] else _tr('msg.modules.service.no'))}"))
        pid_part = f" (pid {st['pid']})" if st.get("pid") else ""
        print(_tr('msg.modules.service.service_running',
            p0=f"{(_tr('msg.modules.service.yes') if st['running'] else _tr('msg.modules.service.no'))}",
            p1=f'{pid_part}',
        ))
        return 0

    if ns.cmd == "run":
        return run()

    return 1
