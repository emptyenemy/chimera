"""Единая папка рантайм-данных приложения.

Раньше state.json/логи/сгенерированные конфиги каждого модуля лежали рядом с
самим модулем (modules/proxy/state.json и т.п.) — россыпь по всему дереву,
неудобно бэкапить и чистить. Теперь всё это уезжает в APP_DIR/data.

DATA_DIR — рядом с программой (папка репозитория при запуске из исходников,
папка exe в собранной версии), а НЕ %APPDATA%: так решено осознанно — будущий
service-режим работает от SYSTEM и должен видеть те же файлы, что и обычный
пользовательский запуск, плюс сама программа портативная и не должна
привязываться к профилю пользователя. CHIMERA_DATA переопределяет путь —
пригождается в тестах и нестандартных раскладках.
"""

import os
import sys
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False) or "__compiled__" in globals():  # собранный .exe (PyInstaller/Nuitka)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()

_override = os.environ.get("CHIMERA_DATA")
DATA_DIR = Path(_override).resolve() if _override else APP_DIR / "data"
LOG_DIR = DATA_DIR / "logs"


def data_path(name: str) -> Path:
    """Путь файла в DATA_DIR. Папку создаёт лениво, по факту обращения."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / name


def log_path(name: str) -> Path:
    """Путь файла в DATA_DIR/logs. Папку создаёт лениво, по факту обращения."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / name


def migrate(old: Path, new: Path) -> None:
    """Одноразовый перенос рантайм-файла со старого места на новое.

    Тихо ничего не делает, если старого файла нет или новый уже существует —
    вызывается на каждом старте, но реально переносит только один раз.
    """
    if new.exists() or not old.exists():
        return
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.replace(new)
    except OSError:
        pass
