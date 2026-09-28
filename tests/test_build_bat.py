"""build.bat: всё, что программе нужно в рантайме, реально попадает в сборку.

Nuitka в --include-data-dir молча пропускает файлы с расширениями «кода» (.bin,
.dll, .exe, .py…) — так из сборки пропали fake-блобы стратегий (.bin), и winws2
в собранной программе не запускался. Для таких файлов нужно явное правило
--include-data-files.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_BAT = (ROOT / "build.bat").read_text(encoding="ascii")

# из nuitka/freezer/IncludedDataFiles.py: default_ignored_suffixes; .py/.pyc в папках
# данных — это инструменты сборки (vendor/build-icons.py), в рантайме не нужны
NUITKA_IGNORED = (".bin", ".dll", ".exe", ".so", ".pyd", ".dylib")


def _data_dirs() -> list[str]:
    return re.findall(r"--include-data-dir=([^=\s]+)=", BUILD_BAT)


def _explicit_rules() -> list[tuple[str, str]]:
    # --include-data-files=SRC_DIR=DEST_DIR/=*.ext
    return re.findall(r"--include-data-files=([^=\s]+)=[^=\s]+=\*(\.\w+)", BUILD_BAT)


def test_data_dirs_found():
    assert "strategies" in _data_dirs() and "ui/web" in _data_dirs()


def test_every_runtime_file_nuitka_skips_has_explicit_rule():
    rules = _explicit_rules()
    missing = []
    for data_dir in _data_dirs():
        for f in (ROOT / data_dir).rglob("*"):
            if not f.is_file() or f.suffix.lower() not in NUITKA_IGNORED or "__pycache__" in f.parts:
                continue
            rel_dir = f.parent.relative_to(ROOT).as_posix()
            if not any(src == rel_dir and ext == f.suffix.lower() for src, ext in rules):
                missing.append(f.relative_to(ROOT).as_posix())
    assert not missing, f"Nuitka выкинет из сборки: {missing[:5]}…"


def test_intermediate_build_dir_is_removed():
    # build\main.build — сгенерированный C-код и объектники; после сборки не нужен
    assert "--remove-output" in BUILD_BAT
