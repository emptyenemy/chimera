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

# При reset читаем не файл целиком (winws2/sing-box за долгую сессию нагенерят
# мегабайты), а хвост: пользователю всё равно интересны последние строки, а не
# история с самого запуска.
_TAIL_BYTES = 256 * 1024


def read_from(path: Path, offset: int = 0) -> dict:
    offset = max(0, int(offset))
    if not path.exists():
        return {"offset": 0, "data": "", "reset": offset != 0}
    try:
        size = path.stat().st_size
        reset = offset == 0 or offset > size  # первый запрос или файл усох → с начала
        start = max(0, size - _TAIL_BYTES) if reset else offset
        with open(path, "rb") as f:
            f.seek(start)
            chunk = f.read()
        if reset and start > 0:
            # начали не с нуля файла — прыжок мог попасть в середину строки,
            # обрывок отдавать не надо: докручиваем до ближайшего перевода строки
            nl = chunk.find(b"\n")
            if nl != -1:
                start += nl + 1
                chunk = chunk[nl + 1:]
    except OSError:
        return {"offset": offset, "data": "", "reset": False}
    return {"offset": start + len(chunk),
            "data": _ANSI_RE.sub(b"", chunk).decode("utf-8", "replace"),
            "reset": reset}
