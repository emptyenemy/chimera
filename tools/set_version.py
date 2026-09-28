"""Подставляет версию в modules/version.py — для сборки релиза в CI.

    python tools/set_version.py v0.2.0     (ведущая v отбрасывается)

Меняется только строка VERSION = "...", остальное содержимое файла остаётся.
"""

import re
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "modules" / "version.py"


def write(version: str, path: Path = VERSION_FILE) -> str:
    version = version.strip().removeprefix("v")
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r'^VERSION = ".*"$', f'VERSION = "{version}"', text, count=1, flags=re.M)
    if n != 1:
        raise RuntimeError(f"в {path} нет строки VERSION = \"...\"")
    path.write_text(new, encoding="utf-8", newline="\n")
    return version


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("использование: python tools/set_version.py v0.2.0")
    print("версия:", write(sys.argv[1]))
