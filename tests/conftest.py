"""Общий conftest: корень репозитория в sys.path, чтобы `import modules...`
работал при запуске `python -m pytest -q` из корня без установки пакета.

Плюс изоляция рантайм-данных (modules/paths.py): DATA_DIR по умолчанию — папка
data/ рядом с репозиторием, а на первом импорте modules/{proxy,winws,hosts,
tgproxy}/manager.py и dns_providers.py вызывается paths.migrate() — одноразовый
перенос СУЩЕСТВУЮЩЕГО modules/*/state.json на новое место. Если это отработает
при обычном импорте в тестах, реальные рабочие файлы уедут из-под приложения.
CHIMERA_DATA уводит DATA_DIR во временную папку, а migrate() на время тестов
глушится совсем — так импорт этих модулей не трогает ничего настоящего."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CHIMERA_DATA", tempfile.mkdtemp(prefix="chimera-tests-data-"))

import modules.paths as _paths  # noqa: E402 - после правки sys.path/CHIMERA_DATA

_paths.migrate = lambda *a, **kw: None
