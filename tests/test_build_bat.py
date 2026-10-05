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
    assert "strategies" in _data_dirs() and "ui/web-next" in _data_dirs()


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
    # каталоги текстов (modules/i18n.py) читаются из modules/locales рядом с программой
    assert dirs.get("modules/locales") == "modules/locales"
    hosts = "upstream/zapret-discord-youtube/.service/hosts"
    assert files.get(hosts) == hosts


def test_new_frontend_is_built_before_nuitka_and_only_the_build_ships():
    # ui/web-next не в git: build.bat собирает его из frontend/ (npm ci + npm run build),
    # а в exe кладёт готовую папку — ни исходники frontend/, ни node_modules
    ci, build, nuitka = (BUILD_BAT.index(s) for s in ("npm ci", "npm run build", "python -m nuitka"))
    assert ci < build < nuitka
    assert "where node" in BUILD_BAT  # без node сборка не падает, а кладёт только прежний фронт
    dirs = _data_dirs()
    assert "ui/web-next" in dirs and "ui/web" not in dirs
    assert not any(d.startswith(("frontend", "node_modules")) for d in dirs)
    assert "--include-data-dir=ui/web-next=ui/web-next" in BUILD_BAT.split("python -m nuitka", 1)[1]


def test_new_frontend_build_is_git_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "ui/web-next/" in ignore and "node_modules/" in ignore


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
    finish = (ROOT / "tools" / "finish_build.py").read_text(encoding="utf-8")
    assert finish.index('"skills"') < finish.index("write_manifest")
    assert finish.index('"AGENTS.md"') < finish.index("write_manifest")


def test_cli_modules_are_reachable_from_main():
    # Nuitka идёт по обычным импортам от main.py: CLI импортируется из main.py напрямую,
    # отдельных --include-module для него не нужно
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from modules.cli" in main_py


def test_intermediate_build_dir_is_removed():
    assert "--remove-output" in BUILD_BAT
    assert "--output-dir=build/%FLAVOR%" in BUILD_BAT


def test_tg_http2_dynamic_dependencies_are_explicitly_in_build():
    # Build invariant: imports from the external .py core are invisible to Nuitka.
    packages = set(re.findall(r"--include-package=([\w.]+)", BUILD_BAT))
    assert {"httpx", "httpcore", "anyio", "idna", "h11", "h2", "hpack", "hyperframe"} <= packages
