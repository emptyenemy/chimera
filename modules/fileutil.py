"""Запись файлов, которые читает не только тот, кто пишет.

Списки и config.json открывают другие процессы и наблюдатель за файлами (modules/filewatch.py);
обычная запись на месте оставляет окно, когда файл уже обрезан, а новое содержимое ещё не
записано. Здесь файл собирается рядом и подменяется одним os.replace.
"""

import os
import tempfile
import time
from pathlib import Path

REPLACE_RETRIES = 5
REPLACE_PAUSE = 0.05


def _drop(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Пишет text во временный файл рядом и подменяет им path. Переводы строк — как у write_text.

    Имя временного файла уникальное: две записи одного файла (окно и командная строка) не
    затрут друг другу заготовку. На Windows os.replace даёт PermissionError, пока кто-то держит
    целевой файл открытым (антивирус, редактор, чтение соседнего потока): это длится доли
    секунды, поэтому пробуем ещё."""
    _atomic_write(path, text, binary=False, encoding=encoding)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    _atomic_write(path, data, binary=True)


def _atomic_write(path: Path, data: str | bytes, *, binary: bool, encoding: str = "utf-8") -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        try:
            stream = os.fdopen(fd, "wb" if binary else "w", encoding=None if binary else encoding)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        with stream:
            stream.write(data)
        for attempt in range(REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == REPLACE_RETRIES - 1:
                    raise
                time.sleep(REPLACE_PAUSE * (attempt + 1))
    except BaseException:
        _drop(tmp)
        raise
