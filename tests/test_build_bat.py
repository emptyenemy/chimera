"""build.bat: всё, что программе нужно в рантайме, реально попадает в сборку.

Nuitka в --include-data-dir молча пропускает файлы с расширениями «кода» (.bin,
.dll, .exe, .py…) — так из сборки пропали fake-блобы стратегий (.bin), и winws2
в собранной программе не запускался. Для таких файлов нужно явное правило
--include-data-files.
"""

import ast
import re
from pathlib import Path

import pytest

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


def test_runtime_data_is_in_build():
    # то, что код читает из дерева программы во время работы (не из data/):
    # списки сайтов (modules/domains.py) и hosts Flowseal (modules/hosts/static_providers.py)
    dirs = dict(re.findall(r"--include-data-dir=([^=\s]+)=([^\s^]+)", BUILD_BAT))
    files = dict(re.findall(r"--include-data-files=([^=\s]+)=([^\s^]+)", BUILD_BAT))
    assert dirs.get("lists") == "lists"
    hosts = "upstream/zapret-discord-youtube/.service/hosts"
    assert files.get(hosts) == hosts


def _tg_core_imports() -> set[str]:
    """Абсолютные импорты ядра tg-ws-proxy. Оно лежит в сборке исходниками и грузится
    во время работы (modules/tgproxy/manager.py), поэтому Nuitka его импортов не видит."""
    names = set()
    for f in (ROOT / "upstream" / "tg-ws-proxy" / "proxy").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names.add(node.module)
    # __future__ — не модуль для сборки; utils.* — только CLI-запуск ядра (main()), не наш путь
    return {n for n in names if n != "__future__" and not n.startswith("utils")}


def test_tg_core_imports_are_in_build():
    if not (ROOT / "upstream" / "tg-ws-proxy" / "proxy").exists():
        pytest.skip("нет сабмодуля upstream/tg-ws-proxy")
    modules = set(re.findall(r"--include-module=([\w.]+)", BUILD_BAT))
    packages = set(re.findall(r"--include-package=([\w.]+)", BUILD_BAT))
    missing = sorted(n for n in _tg_core_imports()
                     if n not in modules and not any(n == p or n.startswith(p + ".") for p in packages))
    assert not missing, f"в сборке не будет модулей ядра tg-ws-proxy: {missing}"


def test_exe_is_also_the_command_line():
    # attach: вывод в консоль запустившего терминала, без своего окна консоли при двойном клике;
    # манифест UAC убран, иначе каждая команда chimera спрашивала бы права администратора
    assert "--windows-console-mode=attach" in BUILD_BAT
    assert "--windows-console-mode=disable" not in BUILD_BAT
    assert "--windows-uac-admin" not in BUILD_BAT


def test_agent_files_are_copied_before_the_manifest():
    # скилл и AGENTS.md лежат рядом с exe и попадают в manifest.txt (обновление их не потеряет)
    skills = BUILD_BAT.index('xcopy /E /I /Y /Q skills "%OUT_DIR%\\skills"')
    agents = BUILD_BAT.index('copy /Y AGENTS.md "%OUT_DIR%\\"')
    manifest = BUILD_BAT.index("--manifest")
    assert skills < manifest and agents < manifest


def test_cli_modules_are_reachable_from_main():
    # Nuitka идёт по обычным импортам от main.py: CLI импортируется из main.py напрямую,
    # отдельных --include-module для него не нужно
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from modules.cli" in main_py


def test_intermediate_build_dir_is_removed():
    # build\main.build — сгенерированный C-код и объектники; после сборки не нужен.
    # Nuitka убирает его сама (--remove-output), а build.bat добивает остаток, если
    # папка осталась от прежних сборок без этого флага
    assert "--remove-output" in BUILD_BAT
    assert re.search(r'rmdir /S /Q "?build\\main\.build"?', BUILD_BAT)
