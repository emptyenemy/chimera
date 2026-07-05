"""Инкрементальное чтение лог-файлов для живого стрима в UI.

Отдаём только то, что добавилось с позиции offset (в байтах), чтобы фронт
дописывал хвост, а не перечитывал весь файл. Если файл обрезали/пересоздали
(новый запуск процесса), сигналим reset=True и читаем с нуля.
"""

import re
from pathlib import Path

# sing-box (и не только) красит свой вывод ANSI-кодами — в терминале ок, но UI
# рисует лог в обычный <pre>, который их не понимает: вместо цвета лезет "[36m" текстом.
_ANSI_RE = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")


def read_from(path: Path, offset: int = 0) -> dict:
    offset = max(0, int(offset))
    if not path.exists():
        return {"offset": 0, "data": "", "reset": offset != 0}
    try:
        size = path.stat().st_size
        reset = offset == 0 or offset > size  # первый запрос или файл усох → с начала
        start = 0 if reset else offset
        with open(path, "rb") as f:
            f.seek(start)
            chunk = f.read()
    except OSError:
        return {"offset": offset, "data": "", "reset": False}
    return {"offset": start + len(chunk),
            "data": _ANSI_RE.sub(b"", chunk).decode("utf-8", "replace"),
            "reset": reset}
