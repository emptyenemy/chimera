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
`check_one()`/`update_one()` — то же самое по одному источнику: сверка всех разом
занимает секунды, а из UI обычно надо дёрнуть только одну строку.

Обновлять умеем лишь то, что лежит в git рядом с нами (сабмодули и бандл): тег —
`fetch` + `checkout` последнего стабильного, бандл — `reset --hard` (апстрим там
делает force-push, `pull` ломается). Пиннутые бинари/шрифты обновлением не
считаются: версия зашита в коде, и менять её должен человек вместе с проверкой
совместимости (схема конфига sing-box ездит от версии к версии).
"""

from modules.i18n import LazySeq, t as _tr

from modules.errors import ChimeraRuntimeError, ChimeraValueError

import importlib.util
import io
import json
import platform
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from pathlib import Path

from modules import i18n, paths

ROOT = Path(__file__).resolve().parent.parent
# Версии git-источников на момент сборки (пишет tools/fetch_bins.py --versions):
# в собранной программе сабмодулей и .git нет, спросить git не у кого.
VERSIONS_FILE = paths.APP_DIR / "versions.json"

_CREATE_NO_WINDOW = 0x08000000

# Официальный API релизов python.org — сверка версии интерпретатора.
# Сам помечает пре-релизы флагом pre_release, так что 3.15-preview отсекается семантически.
_PYTHON_RELEASES_API = "https://www.python.org/api/v2/downloads/release/"
# Запасной источник: www.python.org в РФ режется по SNI (домен у Fastly, соседние
# имена на тех же IP открываются, а с этим TLS-handshake просто виснет), и строка
# Python вечно висела в «не удалось проверить». endoflife.date отдаёт последнюю
# версию каждой ветки и с теми же блокировками доступен.
_PYTHON_EOL_API = "https://endoflife.date/api/python.json"
_HTTP_TIMEOUT = 8

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
def _source_specs():
    return [
        {"name": "Python", "kind": "python",
         "repo": "https://www.python.org/downloads/"},
        {"name": _tr('msg.modules.upstream.strategies_flowseal'), "kind": "tag", "path": "upstream/zapret-discord-youtube",
         "repo": "https://github.com/Flowseal/zapret-discord-youtube"},
        {"name": _tr('msg.modules.upstream.zapret2_engine_winws2'), "kind": "tag", "path": "upstream/zapret2",
         "repo": "https://github.com/bol-van/zapret2"},
        {"name": _tr('msg.modules.upstream.tg_proxy_flowseal'), "kind": "tag", "path": "upstream/tg-ws-proxy",
         "repo": "https://github.com/Flowseal/tg-ws-proxy"},
        {"name": _tr('msg.modules.upstream.winws_bundle_bol_van'), "kind": "commit", "path": "bin/zapret-win-bundle",
         "repo": "https://github.com/bol-van/zapret-win-bundle"},
        {"name": _tr('msg.modules.upstream.proxy_core_sing_box'), "kind": "pin", "version": SINGBOX_VERSION,
         "repo": "https://github.com/SagerNet/sing-box"},
        {"name": _tr('msg.modules.upstream.inter_font'), "kind": "pin", "version": INTER_VERSION,
         "repo": "https://github.com/rsms/inter"},
        {"name": _tr('msg.modules.upstream.jetbrains_mono_font'), "kind": "pin", "version": JETBRAINS_MONO_VERSION,
         "repo": "https://github.com/JetBrains/JetBrainsMono"},
        {"name": _tr('msg.modules.upstream.cheburcheck_rkn_registry'), "kind": "service",
         "repo": "https://cheburcheck.ru"},
    ]


_SOURCES = LazySeq(_source_specs)


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


def _fetch_json(url: str, timeout: int = _HTTP_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "chimera"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _latest_python_stable() -> str | None:
    """Последняя СТАБИЛЬНАЯ версия Python (без a/b/rc). None — оба источника молчат.

    Сначала python.org: опубликованные релизы фильтруем по флагу pre_release самого
    API — пре-релизы (3.15.0a1, 3.15.0rc1) не содержат дефиса, регэкспом бы не
    отсеклись. Если домен недоступен (блокировка по SNI), берём endoflife.date,
    где у каждой ветки есть latest — максимум по ним и есть свежий стабильный.
    """
    data = _fetch_json(_PYTHON_RELEASES_API)
    if data:
        best = None
        for rel in data:
            if not rel.get("is_published") or rel.get("pre_release"):
                continue
            m = re.search(r"\d+\.\d+\.\d+", rel.get("name") or "")
            if m and (best is None or _key(m.group()) > _key(best)):
                best = m.group()
        if best:
            return best

    data = _fetch_json(_PYTHON_EOL_API)
    if not data:
        return None
    best = None
    for cycle in data:
        v = cycle.get("latest")
        if isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v):
            if best is None or _key(v) > _key(best):
                best = v
    return best


# --- текущая версия (локально, без сети) ------------------------------------

def _built_versions() -> dict:
    try:
        return json.loads(VERSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _current(src: dict) -> str:
    kind = src["kind"]
    if kind in ("tag", "commit") and paths.IS_FROZEN:
        stored = _built_versions()
        value = stored.get(src["path"]) or stored.get(src["name"])
        if value:
            return value
        # Старые архивы записывали переведённые названия вместо постоянных путей.
        for lang in ("ru", "en"):
            with i18n.request_language(lang):
                legacy = next((s["name"] for s in _source_specs() if s.get("path") == src["path"]), None)
            if legacy and stored.get(legacy):
                return stored[legacy]
        return "—"
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
        return _tr('msg.modules.upstream.online_service')
    return "—"


def _updatable(src: dict) -> bool:
    """Можно ли обновить источник прямо из программы.

    Только git-источники и только когда их рабочая копия реально лежит рядом:
    в собранном exe сабмодулей нет, а пины/Python/сервис обновляются не нами.
    """
    if src["kind"] not in ("tag", "commit"):
        return False
    return (ROOT / src["path"] / ".git").exists()


def versions() -> list[dict]:
    """Только локальные версии (без сети) — для мгновенного рендера."""
    return [{"name": s["name"], "kind": s["kind"], "version": _current(s),
             "repo": s["repo"], "updatable": _updatable(s)} for s in _SOURCES]


# --- проверка обновлений (сеть) ---------------------------------------------

def _check_one(src: dict) -> dict:
    name, kind, repo = src["name"], src["kind"], src["repo"]
    base = {"name": name, "kind": kind, "repo": repo, "updatable": _updatable(src)}

    if kind in ("tag", "pin"):
        cur = _current(src)
        latest = _latest_tag(repo)
        if latest is None:
            return {**base, "current": cur, "latest": None, "update": False,
                    "error": _tr('msg.modules.upstream.could_not_check_no_network')}
        return {**base, "current": cur, "latest": latest,
                "update": cur != "—" and _key(cur) < _key(latest), "error": None}

    if kind == "python":
        cur = _current(src)
        latest = _latest_python_stable()
        if latest is None:
            return {**base, "current": cur, "latest": None, "update": False,
                    "error": _tr('msg.modules.upstream.could_not_check_no_network')}
        return {**base, "current": cur, "latest": latest,
                "update": _key(cur) < _key(latest), "error": None}

    if kind == "commit":
        path = ROOT / src["path"]
        cur = _git_commit(path)
        loc, rem = _local_head(path), _remote_head(repo)
        if rem is None or loc is None:
            return {**base, "current": cur, "latest": None, "update": False,
                    "error": _tr('msg.modules.upstream.could_not_check_no_network')}
        return {**base, "current": cur, "latest": rem[:7], "update": loc != rem,
                "error": None}

    if kind == "service":
        try:
            from modules import cheburcheck
            st = cheburcheck.status(force=True)
            cur = st.get("version") or "live"
            note = _tr('msg.modules.upstream.registry_updated', p0=f"{st.get('last_update') or '—'}")
            return {**base, "current": cur, "latest": cur, "update": False,
                    "note": note, "error": None}
        except Exception:
            return {**base, "current": "—", "latest": None, "update": False,
                    "error": _tr('msg.modules.upstream.service_unavailable')}

    return {**base, "current": "—", "latest": None, "update": False, "error": _tr('msg.modules.upstream.unknown_type')}


def check_updates(on_result=None) -> list[dict]:
    """Сверяет все источники с их апстримами параллельно.

    on_result(res) зовётся по мере готовности КАЖДОГО источника (из рабочих
    потоков): сверка упирается в сеть, и самый медленный ответ не должен держать
    те, что уже готовы. Возврат — полный список в порядке _SOURCES.
    """
    results = []
    with ThreadPoolExecutor(max_workers=len(_SOURCES)) as ex:
        for fut in as_completed([ex.submit(_check_one, s) for s in _SOURCES]):
            res = fut.result()
            results.append(res)
            if on_result:
                try:
                    on_result(res)
                except Exception:
                    pass  # доставка в UI не должна ронять саму проверку
    order = {s["name"]: i for i, s in enumerate(_SOURCES)}
    return sorted(results, key=lambda r: order.get(r["name"], 0))


def _source(name: str) -> dict:
    for s in _SOURCES:
        if s["name"] == name:
            return s
    raise ChimeraValueError('err.upstream.unknown_source', p0=f'{name!r}')


def check_one(name: str) -> dict:
    """Сверка одного источника — из UI дёргается кнопкой в его строке."""
    return _check_one(_source(name))


# --- обновление (git) -------------------------------------------------------

def _regen_strategies() -> str:
    """Перепорт стратегий Flowseal после обновления сабмодуля.

    Генератор — скрипт, а не пакет (tools/ без __init__.py), поэтому грузим его
    по пути. Обновлённый сабмодуль без перепорта — это свежие хостлисты при
    старых стратегиях, то есть молча разъехавшаяся пара.
    """
    script = ROOT / "tools" / "port_flowseal.py"
    if not script.exists():
        return _tr('msg.modules.upstream.strategy_generator_unavailable_strategies_were_n')
    spec = importlib.util.spec_from_file_location("port_flowseal", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with redirect_stdout(buf):  # генератор пишет отчёт в stdout, окну он не нужен
        mod.main()
    changed = [ln for ln in buf.getvalue().splitlines() if ln.startswith((_tr('msg.modules.upstream.sync'), _tr('msg.modules.upstream.skip')))]
    return _tr('msg.modules.upstream.strategies_regenerated') + (_tr('msg.modules.upstream.resources_updated', p0=f'{len(changed)}') if changed else "")


def _winws_running() -> bool:
    try:
        from modules.winws.manager import _system_pids
        return bool(_system_pids())
    except Exception:
        return False


def _fail(r, what: str) -> None:
    if r is None:
        raise ChimeraRuntimeError('err.upstream.could_not_run_git', p0=what)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise ChimeraRuntimeError('err.upstream.result', p0=what, p1=msg[-1] if msg else _tr('msg.modules.upstream.git_error'))


def update_one(name: str) -> dict:
    """Обновляет один источник до свежей версии апстрима.

    Тег: fetch + checkout последнего стабильного (сабмодуль остаётся в detached
    HEAD — как его и держит git submodule). Коммит: reset --hard на ветку origin,
    потому что bin/zapret-win-bundle регулярно переписывает историю force-push'ем.
    Указатель сабмодуля в основном репозитории не коммитим — это дело человека.
    """
    src = _source(name)
    if not _updatable(src):
        raise ChimeraRuntimeError('err.upstream.cannot_be_updated_from_the_application_no_git_wo', p0=name)
    path = ROOT / src["path"]
    before = _current(src)

    if src["kind"] == "tag":
        _fail(_git(["fetch", "--tags", "--force", "--prune", "origin"], cwd=path, timeout=300),
              "fetch")
        latest = _latest_tag(src["repo"])
        if latest is None:
            raise ChimeraRuntimeError('err.upstream.could_not_fetch_tags_no_network')
        if _key(before) >= _key(latest) and before != "—":
            return {**_check_one(src), "changed": False, "note": _tr('msg.modules.upstream.already_up_to_date')}
        _fail(_git(["checkout", "--force", latest], cwd=path, timeout=120), "checkout")
    else:  # commit
        # бандл — это живые winws2.exe и WinDivert: пока стратегия работает, файлы
        # заняты, и reset свалится на середине, оставив половину бандла старой
        if src["path"].endswith("zapret-win-bundle") and _winws_running():
            raise ChimeraRuntimeError('err.upstream.stop_the_strategy_first_winws2_is_holding_the_bu')
        _fail(_git(["fetch", "--force", "origin"], cwd=path, timeout=600), "fetch")
        r = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=path, timeout=15)
        branch = (r.stdout.strip() if r and r.returncode == 0 else "") or "origin/master"
        _fail(_git(["reset", "--hard", branch], cwd=path, timeout=120), "reset")

    res = _check_one(src)
    after = res.get("current") or _current(src)
    note = f"{before} → {after}"
    if src["path"].endswith("zapret-discord-youtube"):
        note += "; " + _regen_strategies()
    return {**res, "changed": before != after, "note": note}
