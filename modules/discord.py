"""Очистка кэша Discord/PTB/Canary/Development — то же, что пункт «Discord cache
clearing» в service.bat у Flowseal (Cache/Code Cache/GPUCache под %APPDATA%),
но без автозакрытия процесса: закрывать чужое приложение из фонового API — не
дело этой программы, поэтому при запущенном Discord чистка отменяется целиком
с понятной причиной, а не выборочно по вариантам вперемешку с ошибкой.
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraRuntimeError

import os
import shutil
import subprocess
from pathlib import Path

# .exe, папка в %APPDATA%, отображаемое имя
_VARIANTS = [
    ("Discord.exe", "discord", "Discord"),
    ("DiscordPTB.exe", "discordptb", "Discord PTB"),
    ("DiscordCanary.exe", "discordcanary", "Discord Canary"),
    ("DiscordDevelopment.exe", "discorddevelopment", "Discord Development"),
]

# ровно эти подпапки чистит service.bat у каждого варианта
_CACHE_DIRS = ("Cache", "Code Cache", "GPUCache")

_CREATE_NO_WINDOW = 0x08000000


def _appdata() -> Path:
    raw = os.environ.get("APPDATA")
    if not raw:
        raise ChimeraRuntimeError('err.discord.appdata_is_not_set_is_this_windows')
    return Path(raw)


def _running_via_tasklist(names: list[str]) -> set[str]:
    """tasklist — штатный способ узнать запущенные процессы без прав админа."""
    running = set()
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10, creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return running
    text = (r.stdout or "").lower()
    for n in names:
        if n.lower() in text:
            running.add(n)
    return running


def _running_processes(names: list[str]) -> set[str]:
    """Если modules.winproc (модуль «P») уже завёл общий поиск pid по имени —
    используем его, иначе — tasklist. Никого не убиваем, только смотрим."""
    try:
        from modules.winproc import pids_by_name
    except ImportError:
        return _running_via_tasklist(names)

    running = set()
    for n in names:
        try:
            if pids_by_name(n):
                running.add(n)
        except Exception:
            pass  # поиск не удался — считаем «не видно», tasklist как бэкап не подключаем
    return running


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def clear_cache(appdata: Path | None = None, running_check=None) -> dict:
    """Чистит Cache/Code Cache/GPUCache у всех найденных вариантов Discord.

    appdata — переопределение %APPDATA% (тесты, temp-структура папок);
    running_check(names) -> set(names) — переопределение проверки запущенных
    процессов (тесты, без реального tasklist).

    Если хоть один найденный вариант запущен — RuntimeError с именами и ничего
    не удаляется ни у одного (частичная чистка вперемешку с ошибкой запутает
    больше, чем просто попросить закрыть Discord и повторить).
    """
    base = appdata if appdata is not None else _appdata()
    found = [(exe, dirname, label, base / dirname)
             for exe, dirname, label in _VARIANTS if (base / dirname).is_dir()]

    if not found:
        return {"cleared": [], "freed_bytes": 0, "note": _tr('msg.modules.discord.no_installed_discord_found')}

    check = running_check or _running_processes
    running = check([exe for exe, *_rest in found])
    running_labels = [label for exe, _dirname, label, _base_dir in found if exe in running]
    if running_labels:
        raise RuntimeError(_tr('msg.modules.discord.close') + ", ".join(running_labels) + _tr('msg.modules.discord.before_clearing_the_cache'))

    cleared = []
    freed_total = 0
    for _exe, _dirname, label, base_dir in found:
        freed = 0
        cleared_dirs = []
        for sub in _CACHE_DIRS:
            p = base_dir / sub
            if not p.is_dir():
                continue
            freed += _dir_size(p)
            shutil.rmtree(p, ignore_errors=True)
            if not p.exists():
                cleared_dirs.append(sub)
        cleared.append({"name": label, "freed_bytes": freed, "cleared_dirs": cleared_dirs})
        freed_total += freed

    return {"cleared": cleared, "freed_bytes": freed_total}
