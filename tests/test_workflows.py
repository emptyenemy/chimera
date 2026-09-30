"""Workflow релиза: скрипты tools/*.py печатают по-русски, а консоль раннера
windows-latest — cp1252. Без PYTHONUTF8 первый же print() падает с
UnicodeEncodeError, и сборка не доходит даже до Nuitka."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def test_release_job_runs_python_in_utf8():
    job_env = re.search(r"\n  build:\n(?:    .*\n)*?    env:\n((?:      .*\n)+)", RELEASE)
    assert job_env, "у задачи build нет env уровня задачи"
    assert re.search(r'PYTHONUTF8:\s*"1"', job_env.group(1))


def test_release_notes_carry_sha256_of_the_archive():
    # хеш считается уже после сборки архива и попадает в описание релиза: по нему
    # можно сверить скачанный zip; описание берётся из заметок этой версии
    assert "sha256sum" in RELEASE
    assert RELEASE.index("make_archive") < RELEASE.index("sha256sum") < RELEASE.index("gh release create")
    assert "--notes-file" in RELEASE and "--checksums checksums.txt" in RELEASE
    assert "tools/release_notes.py" in RELEASE and "--generate-notes" not in RELEASE
    assert "cd archives && sha256sum Chimera-*-win64*.zip" in RELEASE
    assert 'gh release create "$GITHUB_REF_NAME" "${zips[@]}"' in RELEASE
    assert "needs: build" in RELEASE
    for flavor in ("qt", "webview", "lite"):
        assert f"flavor: {flavor}" in RELEASE
    assert "--flavor ${{ matrix.flavor }}" in RELEASE


def test_release_runs_tools_scripts():
    # проверка выше имеет смысл, пока скрипты tools/ запускаются в этом workflow
    assert "tools/fetch_bins.py" in RELEASE
    assert "tools/smoke_build.py" in RELEASE


def test_release_installs_node_before_build_bat():
    # build.bat собирает новый фронт (npm ci + npm run build), а без node молча пропускает
    assert RELEASE.index("actions/setup-node") < RELEASE.index("call build.bat")


def test_ci_checks_new_frontend():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "actions/setup-node" in ci
    assert ci.index("npm ci") < ci.index("npm run typecheck") < ci.index("npm run build") < ci.index("-m pytest")
