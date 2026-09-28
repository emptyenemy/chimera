"""Самообновление собранной программы из релизов GitHub.

Как это устроено (подробно — docs/RELEASES.md):
  1. check()    — список релизов emptyenemy/chimera, самый свежий под канал
                  (stable — без пре-релизов, beta — с ними), ассет
                  Chimera-<версия>-win64.zip и его SHA256 из поля digest;
  2. download() — архив в data/update/ по частям, со сверкой SHA256;
  3. stage()    — распаковка во временную папку;
  4. write_script() + launch() — apply.cmd запускается отдельным процессом, а
                  программа выходит: работающий exe и загруженные DLL не
                  перезаписать, пока процесс жив. Скрипт дожидается выхода,
                  копирует текущую версию в rollback/, кладёт новую поверх
                  (robocopy /MIR), при ошибке возвращает старую и запускает
                  программу снова.

Ставится только по кнопке и только в собранной программе: из исходников
обновляются через git. Без токена: пока репозиторий приватный, GitHub
отвечает 404 — это «не удалось проверить», а не ошибка программы.
"""

import hashlib
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from modules import paths
from modules.version import VERSION, is_newer, parse

REPO = "emptyenemy/chimera"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
ASSET_RE = re.compile(r"^Chimera-.+-win64\.zip$")
EXE_NAME = "Chimera.exe"
SERVICE_TASK = "CHIMERA-Service"  # modules/service.py: TASK_NAME

UPDATE_DIR = paths.DATA_DIR / "update"
LOG_PATH = paths.LOG_DIR / "update.log"

# Что обновление не трогает. data/ — целиком (состояние модулей, логи, сама
# папка update/); файлы — пользовательские настройки и выбор списков. Задаются
# полными путями: по одному имени robocopy исключил бы и тёзок в чужих папках
# (config.json бывает и внутри пакетов).
KEEP_DIRS = ("data",)
KEEP_FILES = (
    "config.json",
    "strategies/hostlists/list-general-user.txt",
    "strategies/hostlists/ipset-user.txt",
    "strategies/hostlists/ipset-all.txt",
    "strategies/hostlists/ipset-all.txt.backup",
)

_HTTP_TIMEOUT = 15
_CHUNK = 256 * 1024
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


# --- проверка ---------------------------------------------------------------------

def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "chimera", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _zip_asset(release: dict) -> dict | None:
    return next((a for a in release.get("assets") or [] if ASSET_RE.match(a.get("name", ""))), None)


def pick_release(releases: list[dict], channel: str) -> dict | None:
    """Самый свежий подходящий релиз: не черновик, с архивом, пре-релиз — только в beta.

    Выбор по версии, а не по порядку: GitHub сортирует по дате создания, и
    хотфикс старой ветки мог бы оказаться «новее» свежего релиза.
    """
    best, best_key = None, None
    for r in releases or []:
        if r.get("draft") or (r.get("prerelease") and channel != "beta"):
            continue
        key = parse(r.get("tag_name", ""))
        if key is None or _zip_asset(r) is None:
            continue
        if best_key is None or key > best_key:
            best, best_key = r, key
    return best


def _asset_info(asset: dict) -> dict:
    digest = asset.get("digest") or ""
    sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
    return {"name": asset["name"], "url": asset.get("browser_download_url"),
            "size": asset.get("size") or 0, "sha256": sha}


def check(channel: str = "stable", current: str = VERSION, fetch=_fetch_json) -> dict:
    """Есть ли версия новее current в канале. Сеть и 404 — поле error, не исключение."""
    base = {"current": current, "latest": None, "update": False, "installable": False,
            "notes": "", "url": None, "asset": None, "error": None}
    try:
        releases = fetch(RELEASES_API)
    except urllib.error.HTTPError as e:
        why = "релизов не видно — репозиторий закрыт или релизов ещё нет" if e.code == 404 else f"GitHub ответил {e.code}"
        return {**base, "error": f"не удалось проверить: {why}"}
    except (urllib.error.URLError, OSError, ValueError):
        return {**base, "error": "не удалось проверить (нет сети?)"}

    rel = pick_release(releases, channel)
    if rel is None:
        return base
    asset = _asset_info(_zip_asset(rel))
    latest = rel["tag_name"].removeprefix("v")
    update = is_newer(latest, current)
    return {**base, "latest": latest, "update": update,
            # ставим только в сборке и только то, что есть с чем сверить
            "installable": update and paths.IS_FROZEN and bool(asset["sha256"] and asset["url"]),
            "notes": rel.get("body") or "", "url": rel.get("html_url"), "asset": asset}


# --- скачивание и распаковка ------------------------------------------------------

def download(asset: dict, dest_dir: Path, progress=None, opener=urllib.request.urlopen) -> Path:
    """Качает архив в dest_dir; SHA256 не сошёлся — файла нет, RuntimeError."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / asset["name"]
    part = final.with_name(final.name + ".part")
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(asset["url"], headers={"User-Agent": "chimera"})
    try:
        with opener(req, timeout=60) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or asset.get("size") or 0)
            while chunk := resp.read(_CHUNK):
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest() != (asset.get("sha256") or "").lower():
            raise RuntimeError("SHA256 скачанного архива не совпадает с опубликованным — "
                               "файл повреждён или подменён, установка отменена")
        part.replace(final)
        return final
    finally:
        part.unlink(missing_ok=True)


def stage(zip_path: Path, dest: Path) -> Path:
    """Распаковывает архив в dest; возвращает папку, где лежит Chimera.exe."""
    if dest.exists():
        shutil.rmtree(dest)
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest)  # zipfile сам отбрасывает абсолютные пути и «..»
    except (zipfile.BadZipFile, OSError) as e:
        raise RuntimeError(f"архив обновления не распаковался: {e}") from e
    exe = next(dest.rglob(EXE_NAME), None)
    if exe is None:
        raise RuntimeError(f"в архиве обновления нет {EXE_NAME}")
    return exe.parent


# --- установка --------------------------------------------------------------------

def _q(p) -> str:
    return f'"{p}"'


def write_script(app_dir: Path, staged: Path, pid: int, restart_service: bool, relaunch: bool,
                 script: Path, log: Path, rollback: Path) -> Path:
    """Пишет apply.cmd: дождаться выхода pid, сохранить текущую версию, положить новую, при ошибке — вернуть."""
    app, st, rb, lg = (str(Path(p)) for p in (app_dir, staged, rollback, log))
    xd = " ".join(_q(Path(app) / d) for d in KEEP_DIRS)
    xf = " ".join(_q(Path(app) / f.replace("/", "\\")) for f in KEEP_FILES)
    # /R:2 /W:1 — занятый файл не ждать по умолчанию «миллион раз по 30 с»; /NP /NJH /NJS — лог короче
    rc = "/R:2 /W:1 /NP /NJH /NJS"
    lines = [
        "@echo off",
        "chcp 65001 >nul",  # пути с кириллицей — дальше файл читается как UTF-8
        "setlocal",
        f'set "LOG={lg}"',
        'echo [%date% %time%] обновление: начало>>"%LOG%"',
        # ждём выхода программы (не дольше 2 минут), sleep — через ping: timeout
        # у процесса без консоли падает сразу и превратил бы ожидание в busy-loop
        "set /a N=0",
        ":wait",
        f'tasklist /FI "PID eq {pid}" /NH 2>nul | find "{pid}" >nul',
        "if errorlevel 1 goto gone",
        "set /a N+=1",
        "if %N% GEQ 120 goto gone",
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":gone",
        'echo [%date% %time%] программа закрыта, сохраняю текущую версию>>"%LOG%"',
        f'robocopy {_q(app)} {_q(rb)} /MIR /XD {xd} {rc} >>"%LOG%"',
        "if errorlevel 8 goto nosave",
        'echo [%date% %time%] ставлю новую версию>>"%LOG%"',
        f'robocopy {_q(st)} {_q(app)} /MIR /XD {xd} /XF {xf} {rc} >>"%LOG%"',
        "if errorlevel 8 goto rollback",
        'echo [%date% %time%] готово>>"%LOG%"',
        f'rmdir /S /Q {_q(Path(st).parent)} >nul 2>&1',
        "set RESULT=0",
        "goto after",
        ":nosave",
        'echo [%date% %time%] не удалось сохранить текущую версию — обновление отменено>>"%LOG%"',
        "set RESULT=1",
        "goto after",
        ":rollback",
        'echo [%date% %time%] ошибка копирования — откат на прежнюю версию>>"%LOG%"',
        f'robocopy {_q(rb)} {_q(app)} /MIR /XD {xd} /XF {xf} {rc} >>"%LOG%"',
        "set RESULT=2",
        ":after",
    ]
    if restart_service:
        lines.append(f'schtasks /Run /TN "{SERVICE_TASK}" >>"%LOG%" 2>&1')
    if relaunch:
        lines.append(f'start "" {_q(Path(app) / EXE_NAME)}')
    lines.append("exit /b %RESULT%")

    script.parent.mkdir(parents=True, exist_ok=True)
    Path(lg).parent.mkdir(parents=True, exist_ok=True)
    # CRLF: cmd.exe промахивается по goto в LF-файлах; UTF-8 без BOM — BOM cmd счёл бы частью команды
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
    return script


def launch(script: Path) -> None:
    """Запускает apply.cmd отдельно от программы — он переживёт её выход."""
    subprocess.Popen(["cmd", "/c", str(script)], close_fds=True,
                     creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW)
