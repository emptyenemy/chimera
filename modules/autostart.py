"""Автозапуск приложения вместе с Windows.

Способ — задача в «Планировщике заданий» (Task Scheduler), которая срабатывает
при входе пользователя в систему. Почему именно так, а не ярлык в «Автозагрузке»
или ключ реестра Run:

  main.py сам повышается до администратора через UAC. Ярлык/Run-ключ при каждом
  старте Windows показывали бы окно UAC — неудобно. Задача планировщика с
  «наивысшими правами» (RunLevel=HighestAvailable) и интерактивным токеном
  запускает приложение сразу повышенным, на рабочем столе пользователя и БЕЗ
  запроса UAC. Пароль не хранится.

Источник правды — сама задача в планировщике (есть/нет), отдельно в config.json
ничего не дублируем, чтобы состояние не разъезжалось.
"""

from modules.i18n import t as _tr

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape, unescape

from modules import paths

ROOT = Path(__file__).parent.parent
MAIN_PY = ROOT / "main.py"
TASK_NAME = "CHIMERA"
# С Windows программа стартует сразу в трей, без окна (см. ui/backend_qt.py). --window нужен
# с тех пор, как chimera по умолчанию командная строка (modules/cli/entry.py): без него
# запуск из консоли печатал бы справку. Задачи со старым аргументом одним --tray по-прежнему
# открывают окно, а refresh() приводит их к новому виду.
TRAY_ARG = "--tray"
WINDOW_ARG = "--window"
LAUNCH_ARGS = f"{WINDOW_ARG} {TRAY_ARG}"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_supported() -> bool:
    return sys.platform == "win32"


def _current_user() -> str:
    """Текущий пользователь в виде DOMAIN\\user (для триггера и принципала задачи)."""
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def _launch_target() -> tuple[str, str]:
    """(команда, аргументы) для запуска приложения.

    Собранный .exe запускаем напрямую; из исходников — через pythonw.exe
    (без консольного окна), передавая путь к main.py. В обоих случаях с --window --tray.
    """
    if paths.IS_FROZEN:
        return sys.executable, LAUNCH_ARGS
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")  # оконный интерпретатор — без чёрной консоли
    command = str(pyw if pyw.exists() else exe)
    return command, f'"{MAIN_PY}" {LAUNCH_ARGS}'


def _task_xml() -> str:
    user = escape(_current_user())
    command, arguments = _launch_target()
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Description>Автозапуск CHIMERA вместе с Windows</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <LogonTrigger>\n"
        "      <Enabled>true</Enabled>\n"
        f"      <UserId>{user}</UserId>\n"
        "    </LogonTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        f"      <UserId>{user}</UserId>\n"
        "      <LogonType>InteractiveToken</LogonType>\n"
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


def is_enabled() -> bool:
    """Есть ли задача автозапуска в планировщике."""
    if not is_supported():
        return False
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, creationflags=_NO_WINDOW,
    )
    return r.returncode == 0


def enable() -> None:
    """Создаёт (или пересоздаёт) задачу автозапуска. Нужны права администратора."""
    xml = _task_xml()
    # schtasks /XML требует файл в UTF-16; пишем во временный и удаляем после
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        Path(path).write_text(xml, encoding="utf-16")
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or _tr('msg.modules.autostart.schtasks_create_failed')).strip())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def disable() -> None:
    """Удаляет задачу автозапуска. Тихо игнорирует отсутствие задачи."""
    r = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    if r.returncode != 0 and is_enabled():
        raise RuntimeError((r.stderr or r.stdout or _tr('msg.modules.autostart.schtasks_delete_failed')).strip())


def _decode(raw: bytes) -> str:
    # schtasks пишет XML в кодировке консоли, хотя в заголовке значится UTF-16;
    # на случай настоящего UTF-16 (с BOM) — тоже разбираем
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("oem" if sys.platform == "win32" else "latin-1", errors="replace")


def _registered_target() -> tuple[str, str] | None:
    """(команда, аргументы) из действия существующей задачи; None — задачи нет."""
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/XML"],
        capture_output=True, creationflags=_NO_WINDOW,
    )
    if r.returncode != 0:
        return None
    xml = _decode(r.stdout or b"")
    command = re.search(r"<Command>(.*?)</Command>", xml, re.S)
    arguments = re.search(r"<Arguments>(.*?)</Arguments>", xml, re.S)
    quotes = {"&quot;": '"', "&apos;": "'"}  # планировщик может отдать кавычки сущностями
    return (unescape(command.group(1), quotes).strip() if command else "",
            unescape(arguments.group(1), quotes).strip() if arguments else "")


def refresh() -> bool:
    """Пересоздаёт задачу, если она запускает не то, что нужно сейчас.

    Задачи из прошлых версий стартовали без --tray (сразу с окном), а после
    переезда программы в другую папку указывают на старый путь. Зовётся на
    старте окна; нужны права администратора. True — задача пересоздана.
    """
    if not is_supported():
        return False
    current = _registered_target()
    if current is None:
        return False
    command, arguments = _launch_target()
    if current == (command, arguments):
        return False
    enable()
    return True


def set_enabled(value: bool) -> bool:
    """Включает/выключает автозапуск. Возвращает фактическое состояние."""
    if value:
        enable()
    else:
        disable()
    return is_enabled()
