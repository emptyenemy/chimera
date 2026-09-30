"""Подставляет версию в modules/version.py — для сборки релиза в CI.

    python tools/set_version.py v0.2.0     (ведущая v отбрасывается)

Меняется только строка VERSION = "...", остальное содержимое файла остаётся.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "modules" / "version.py"
sys.path.insert(0, str(ROOT))

from modules.version import parse  # noqa: E402


def write(version: str, path: Path = VERSION_FILE) -> str:
    version = version.strip().removeprefix("v")
    # тег вида vtest или v1.2 — не версия: лучше уронить сборку, чем выпустить exe
    # с версией, которую самообновление не сможет сравнить
    if parse(version) is None:
        raise ValueError(f"{version!r} — не версия: нужен тег вида v0.2.0 или v0.3.0-beta.1")
    raw = path.read_bytes()
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    new, n = re.subn(r'^VERSION = ".*"$', f'VERSION = "{version}"', text, count=1, flags=re.M)
    if n != 1:
        raise RuntimeError(f"в {path} нет строки VERSION = \"...\"")
    path.write_bytes(new.encode("utf-8").replace(b"\n", newline))
    return version


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("использование: python tools/set_version.py v0.2.0")
    print("версия:", write(sys.argv[1]))
