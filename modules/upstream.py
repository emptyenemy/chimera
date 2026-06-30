"""Версии внешних источников, из которых собран проект, и проверка обновлений.

Сводит в одно место ВСЁ, что мы тянем со стороны, с разными схемами версий:
  • сабмодули по тегам   — Flowseal/zapret-discord-youtube (стратегии),
                           bol-van/zapret2 (движок winws2), Flowseal/tg-ws-proxy;
  • git-клон по коммитам — bin/zapret-win-bundle (winws/WinDivert/blockcheck, без тегов);
  • пиннутый бинарь      — sing-box (версия зашита в modules/proxy/manager.py);
  • онлайн-сервис        — cheburcheck.ru (живой реестр РКН, версия из /status);
  • интерпретатор        — Python (текущий рантайм vs последний стабильный с python.org).

`versions()` — локально и мгновенно (без сети). `check_updates()` — сверяет с
GitHub (`git ls-remote`, без токена) параллельно; для сервиса дёргает /status.
"""

import json
import platform
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_CREATE_NO_WINDOW = 0x08000000

# Официальный API релизов python.org — сверка версии интерпретатора.
# Сам помечает пре-релизы флагом pre_release, так что 3.15-preview отсекается семантически.
_PYTHON_RELEASES_API = "https://www.python.org/api/v2/downloads/release/"

try:
    from modules.proxy.manager import SINGBOX_VERSION
except Exception:  # pragma: no cover — на случай поломки импорта proxy
    SINGBOX_VERSION = None

# Шрифты UI зашиты в ui/web/fonts/ (woff2, скачаны с GitHub-релизов апстрима,
# не из Google Fonts CDN) — версия пиннута тут же, как у sing-box.
INTER_VERSION = "4.1"
JETBRAINS_MONO_VERSION = "2.304"

# kind: tag — сабмодуль по тегам; commit — git-клон по коммитам; pin — пиннутый
#       бинарь/ассет (версия в коде, src["version"]); service — онлайн-сервис;
#       python — интерпретатор (python.org).
_SOURCES = [
    {"name": "Python", "kind": "python",
     "repo": "https://www.python.org/downloads/"},
    {"name": "Стратегии (Flowseal)", "kind": "tag", "path": "upstream/zapret-discord-youtube",
     "repo": "https://github.com/Flowseal/zapret-discord-youtube"},
    {"name": "Движок zapret2 (winws2)", "kind": "tag", "path": "upstream/zapret2",
     "repo": "https://github.com/bol-van/zapret2"},
    {"name": "TG-прокси (Flowseal)", "kind": "tag", "path": "upstream/tg-ws-proxy",
     "repo": "https://github.com/Flowseal/tg-ws-proxy"},
    {"name": "winws-бандл (bol-van)", "kind": "commit", "path": "bin/zapret-win-bundle",
     "repo": "https://github.com/bol-van/zapret-win-bundle"},
    {"name": "Прокси-ядро (sing-box)", "kind": "pin", "version": SINGBOX_VERSION,
     "repo": "https://github.com/SagerNet/sing-box"},
    {"name": "Шрифт Inter", "kind": "pin", "version": INTER_VERSION,
     "repo": "https://github.com/rsms/inter"},
    {"name": "Шрифт JetBrains Mono", "kind": "pin", "version": JETBRAINS_MONO_VERSION,
     "repo": "https://github.com/JetBrains/JetBrainsMono"},
    {"name": "CheburCheck (реестр РКН)", "kind": "service",
     "repo": "https://cheburcheck.ru"},
]


# --- git-хелперы ------------------------------------------------------------

def _git(args: list[str], cwd: Path | None = None, timeout: int = 15):
    cmd = ["git"] + (["-C", str(cwd)] if cwd else []) + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=_CREATE_NO_WINDOW, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _git_tag(path: Path) -> str:
    """Тег чекаута (git describe), либо короткий хеш, либо '—'."""
    if not path.exists():
        return "—"
    r = _git(["describe", "--tags", "--always"], cwd=path, timeout=5)
    return (r.stdout.strip() or "—") if (r and r.returncode == 0) else "—"


def _git_commit(path: Path) -> str:
    if not path.exists():
        return "—"
    r = _git(["rev-parse", "--short", "HEAD"], cwd=path, timeout=5)
    return (r.stdout.strip() or "—") if (r and r.returncode == 0) else "—"


def _local_head(path: Path) -> str | None:
    r = _git(["rev-parse", "HEAD"], cwd=path, timeout=5)
    return r.stdout.strip() if (r and r.returncode == 0) else None


def _key(tag: str) -> list:
    """Натуральный ключ сравнения версий: '1.9.9c' > '1.9.9b' > '1.9.9'.

    Тег режется на числовые и буквенные сегменты; число — (n, ''), буква — (-1, s).
    Так '1.9.9' (короче) < '1.9.9c', а '1.9.10' > '1.9.9' (числа, не лексикографика).
    """
    parts = re.findall(r"\d+|[A-Za-z]+", tag.lstrip("vV"))
    return [(int(p), "") if p.isdigit() else (-1, p.lower()) for p in parts]


def _latest_tag(repo: str) -> str | None:
    """Последний СТАБИЛЬНЫЙ тег (без -alpha/-beta/-rc) репозитория. None — нет связи."""
    r = _git(["ls-remote", "--tags", "--refs", repo])
    if not r or r.returncode != 0:
        return None
    tags = [ln.split("refs/tags/", 1)[1].strip()
            for ln in r.stdout.splitlines() if "refs/tags/" in ln]
    tags = [t for t in tags if "-" not in t]  # отсекаем пре-релизы (важно для sing-box)
    return max(tags, key=_key) if tags else None


def _remote_head(repo: str) -> str | None:
    r = _git(["ls-remote", repo, "HEAD"])
    if not r or r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split()[0].strip()


def _latest_python_stable() -> str | None:
    """Последняя СТАБИЛЬНАЯ версия Python с python.org (без a/b/rc). None — нет связи.

    Опубликованные релизы фильтруем по флагу pre_release самого API — пре-релизы
    (3.15.0a1, 3.15.0rc1) не содержат дефиса, регэкспом бы не отсеклись."""
    req = urllib.request.Request(_PYTHON_RELEASES_API, headers={"User-Agent": "chimera"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    best = None
    for rel in data:
        if not rel.get("is_published") or rel.get("pre_release"):
            continue
        m = re.search(r"\d+\.\d+\.\d+", rel.get("name") or "")
        if m and (best is None or _key(m.group()) > _key(best)):
            best = m.group()
    return best


# --- текущая версия (локально, без сети) ------------------------------------

def _current(src: dict) -> str:
    kind = src["kind"]
    if kind == "tag":
        return _git_tag(ROOT / src["path"])
    if kind == "commit":
        return _git_commit(ROOT / src["path"])
    if kind == "pin":
        v = src.get("version")
        return f"v{v}" if v else "—"
    if kind == "python":
        return platform.python_version()
    if kind == "service":
        return "онлайн-сервис"
    return "—"


def versions() -> list[dict]:
    """Только локальные версии (без сети) — для мгновенного рендера."""
    return [{"name": s["name"], "kind": s["kind"], "version": _current(s),
             "repo": s["repo"]} for s in _SOURCES]


# --- проверка обновлений (сеть) ---------------------------------------------

def _check_one(src: dict) -> dict:
    name, kind, repo = src["name"], src["kind"], src["repo"]
    base = {"name": name, "kind": kind, "repo": repo}

    if kind in ("tag", "pin"):
        cur = _current(src)
        latest = _latest_tag(repo)
        if latest is None:
            return {**base, "current": cur, "latest": None, "update": False,
                    "error": "не удалось проверить (нет сети?)"}
        return {**base, "current": cur, "latest": latest,
                "update": cur != "—" and _key(cur) < _key(latest), "error": None}

    if kind == "python":
        cur = _current(src)
        latest = _latest_python_stable()
        if latest is None:
            return {**base, "current": cur, "latest": None, "update": False,
                    "error": "не удалось проверить (нет сети?)"}
        return {**base, "current": cur, "latest": latest,
                "update": _key(cur) < _key(latest), "error": None}

    if kind == "commit":
        path = ROOT / src["path"]
        cur = _git_commit(path)
        loc, rem = _local_head(path), _remote_head(repo)
        if rem is None or loc is None:
            return {**base, "current": cur, "latest": None, "update": False,
                    "error": "не удалось проверить (нет сети?)"}
        return {**base, "current": cur, "latest": rem[:7], "update": loc != rem,
                "error": None}

    if kind == "service":
        try:
            from modules import cheburcheck
            st = cheburcheck.status(force=True)
            cur = st.get("version") or "live"
            note = f"реестр обновлён: {st.get('last_update') or '—'}"
            return {**base, "current": cur, "latest": cur, "update": False,
                    "note": note, "error": None}
        except Exception:
            return {**base, "current": "—", "latest": None, "update": False,
                    "error": "сервис недоступен"}

    return {**base, "current": "—", "latest": None, "update": False, "error": "неизвестный тип"}


def check_updates() -> list[dict]:
    """Сверяет все источники с их апстримами параллельно."""
    with ThreadPoolExecutor(max_workers=len(_SOURCES)) as ex:
        return list(ex.map(_check_one, _SOURCES))
