"""Общий журнал приложения: data/logs/app.log.

Сюда пишутся события самой программы, у которых нет своего модуля-владельца лога:
очистка хвостов после аварийного завершения, «Выключить всё» и подобное. Файл
дописывается, поэтому его размер ограничен: дойдя до предела, он уезжает в app.log.1
(прежний app.log.1 затирается) — старше двух файлов история не хранится.
"""

import os
import time
from pathlib import Path

from . import paths

LOG_PATH = paths.log_path("app.log")
MAX_BYTES = 1024 * 1024


def _rotate(path: Path) -> None:
    try:
        if path.stat().st_size < MAX_BYTES:
            return
    except OSError:
        return
    try:
        os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass  # занят другим процессом — ротация подождёт следующей записи


def write(message: str, path: Path | None = None) -> None:
    """Дописывает строку с меткой времени. Журнал вспомогательный: сбой записи
    (диск, права) не должен ронять то, о чём пишем."""
    target = path or LOG_PATH
    _rotate(target)
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass
