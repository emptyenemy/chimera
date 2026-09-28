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


def test_release_runs_tools_scripts():
    # проверка выше имеет смысл, пока скрипты tools/ запускаются в этом workflow
    assert "tools/fetch_bins.py" in RELEASE
    assert "tools/smoke_build.py" in RELEASE
