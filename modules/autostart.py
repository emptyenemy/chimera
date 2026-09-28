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

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from modules import paths

ROOT = Path(__file__).parent.parent
MAIN_PY = ROOT / "main.py"
TASK_NAME = "CHIMERA"

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
    (без консольного окна), передавая путь к main.py.
    """
    if paths.IS_FROZEN:
        return sys.executable, ""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")  # оконный интерпретатор — без чёрной консоли
    command = str(pyw if pyw.exists() else exe)
    return command, f'"{MAIN_PY}"'


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
            raise RuntimeError((r.stderr or r.stdout or "schtasks /Create не удался").strip())
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
        raise RuntimeError((r.stderr or r.stdout or "schtasks /Delete не удался").strip())


def set_enabled(value: bool) -> bool:
    """Включает/выключает автозапуск. Возвращает фактическое состояние."""
    if value:
        enable()
    else:
        disable()
    return is_enabled()
