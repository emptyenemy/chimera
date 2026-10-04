"""Запись файлов, которые читает не только тот, кто пишет.

Списки и config.json открывают другие процессы и наблюдатель за файлами (modules/filewatch.py);
обычная запись на месте оставляет окно, когда файл уже обрезан, а новое содержимое ещё не
записано. Здесь файл собирается рядом и подменяется одним os.replace.
"""

import os
import tempfile
import time
from pathlib import Path

from modules.errors import ChimeraPermissionError

# Пока файл открыт другим процессом (окно и служба читают состояние, winws2 и sing-box — свои
# списки, Defender проверяет свежую запись), os.replace даёт PermissionError. Ждём с нарастающей
# паузой — всего около трёх секунд, потом говорим понятно, а не голым «[Errno 13]».
REPLACE_RETRIES = 12
REPLACE_PAUSE = 0.05


def _drop(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8", *, prepare=None) -> None:
    """Пишет text во временный файл рядом и подменяет им path. Переводы строк — как у write_text.

    Имя временного файла уникальное: две записи одного файла (окно и командная строка) не
    затрут друг другу заготовку. На Windows os.replace даёт PermissionError, пока кто-то держит
    целевой файл открытым (антивирус, редактор, чтение соседнего потока): это длится доли
    секунды, поэтому пробуем ещё. prepare(tmp) — до подмены, например закрыть права на файл
    с секретами: подменённый файл уже не бывает открытым для всех."""
    _atomic_write(path, text, binary=False, encoding=encoding, prepare=prepare)


def atomic_write_bytes(path: Path, data: bytes, *, prepare=None) -> None:
    _atomic_write(path, data, binary=True, prepare=prepare)


def replace_file(source, target) -> None:
    """os.replace, который ждёт, пока целевой файл отпустят (переименование списка, подмена
    готового файла). Не дождался — понятная ошибка с именем файла."""
    target = Path(target)
    for attempt in range(REPLACE_RETRIES):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                raise ChimeraPermissionError("err.file.busy", name=target.name) from None
            time.sleep(REPLACE_PAUSE * (attempt + 1))


def _atomic_write(path: Path, data: str | bytes, *, binary: bool, encoding: str = "utf-8", prepare=None) -> None:
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
        if prepare is not None:
            prepare(Path(tmp))
        replace_file(tmp, path)
    except BaseException:
        _drop(tmp)
        raise
