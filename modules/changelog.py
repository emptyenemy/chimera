"""Журнал изменений data/changes.log: кто и что менял.

Строка: время, источник, команда, результат — через табуляцию. Источник `cli` — команда
chimera, `file` — правка файла напрямую, замеченная наблюдателем (modules/filewatch.py).
"""

from datetime import datetime
from pathlib import Path

from modules import paths

CHANGES_LOG = paths.data_path("changes.log")


def record(source: str, command: str, ok: bool, path: Path | None = None) -> None:
    try:
        with open(path or CHANGES_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{source}\t{command}\t{'ok' if ok else 'error'}\n")
    except OSError:
        pass  # журнал вспомогательный: не мешаем тому, что записываем
