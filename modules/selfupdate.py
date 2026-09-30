"""Самообновление собранной программы из релизов GitHub.

Как это устроено (подробно — docs/RELEASES.md):
  1. check()    — список релизов emptyenemy/chimera, самый свежий под канал
                  (stable — без пре-релизов, beta — с ними), ассет
                  Chimera-<версия>-win64.zip и его SHA256 из поля digest;
  2. download() — архив в data/update/ по частям, со сверкой SHA256;
  3. stage()    — распаковка во временную папку;
  4. write_script() — копирует текущую версию в rollback/ (пока программа ещё
                  жива: не вышло — обновление отменяется, ничего не тронуто) и
                  пишет apply.cmd;
  5. launch()   — apply.cmd запускается отдельным процессом, а программа
                  выходит: работающий exe и загруженные DLL не перезаписать,
                  пока процесс жив. Скрипт дожидается выхода, кладёт новую
                  версию поверх, удаляет файлы, которых в ней больше нет, при
                  ошибке возвращает старую и запускает программу снова.

Своими программа считает только файлы из manifest.txt — списка, который
сборка кладёт рядом с exe. Всё прочее в папке (распаковали на рабочий стол,
положили рядом свои файлы) обновление не видит и не трогает; поэтому и нет
robocopy /MIR: он удалил бы в папке всё, чего нет в новой версии.

Ставится только по кнопке и только в собранной программе: из исходников
обновляются через git. Без токена: пока репозиторий приватный, GitHub
отвечает 404 — это «не удалось проверить», а не ошибка программы.
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraRuntimeError

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
from modules.version import FLAVOR, VERSION, asset_suffix, is_newer, parse

REPO = "emptyenemy/chimera"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
ASSET_RE = re.compile(r"^Chimera-.+-win64" + re.escape(asset_suffix(FLAVOR)) + r"\.zip$")
EXE_NAME = "Chimera.exe"
MANIFEST = "manifest.txt"  # список файлов релиза, пишет build.bat (tools/fetch_bins.py --manifest)
SERVICE_TASK = "CHIMERA-Service"  # modules/service.py: TASK_NAME

UPDATE_DIR = paths.DATA_DIR / "update"
LOG_PATH = paths.LOG_DIR / "update.log"

# Файлы пользователя, которые обновление не перезаписывает и не удаляет, даже если
# релиз принесёт файл с тем же путём. data/ (состояние модулей, логи, сама папка
# update/) защищать отдельно не нужно: в manifest.txt релиза её нет, а чужого
# обновление не трогает. Пути — от корня программы: по одному имени задели бы и
# тёзок в чужих папках (config.json бывает и внутри пакетов).
KEEP_FILES = (
    "config.json",
    "strategies/hostlists/list-general-user.txt",
    "strategies/hostlists/ipset-user.txt",
    "strategies/hostlists/ipset-all.txt",
    "strategies/hostlists/ipset-all.txt.backup",
    # слоты фейков: релиз приносит значение по умолчанию, а выбранный под провайдера
    # блоб копируется прямо в файл слота (modules/winws/filters.py, set_fake)
    "strategies/assets/ACTIVE_DISCORD_UDP.bin",
    "strategies/assets/ACTIVE_GAME_UDP.bin",
)
# Папки, которые пользователь правит прямо в программе (списки сайтов). Из релиза
# в них докладываются только новые файлы; уже лежащие не перезаписываются и не
# удаляются, даже если в релизе файл поменялся или исчез.
USER_DIRS = ("lists",)


def _in_user_dir(rel: str) -> bool:
    return any(rel == d or rel.startswith(d + "/") for d in USER_DIRS)

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
        why = _tr('msg.modules.selfupdate.releases_are_unavailable_repository_is_private_o') if e.code == 404 else _tr('msg.modules.selfupdate.github_returned',
            p0=f'{e.code}',
        )
        return {**base, "error": _tr('msg.modules.selfupdate.could_not_check', p0=f'{why}')}
    except (urllib.error.URLError, OSError, ValueError):
        return {**base, "error": _tr('msg.modules.selfupdate.could_not_check_no_network')}

    rel = pick_release(releases, channel)
    if rel is None:
        return base
    asset = _asset_info(_zip_asset(rel))
    latest = rel["tag_name"].removeprefix("v")
    update = is_newer(latest, current)
    return {**base, "latest": latest, "update": update,
            # ставим только в сборке, только поверх известного списка своих файлов
            # и только то, что есть с чем сверить
            "installable": (update and paths.IS_FROZEN and (paths.APP_DIR / MANIFEST).exists()
                            and bool(asset["sha256"] and asset["url"])),
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
            raise ChimeraRuntimeError('err.selfupdate.the_downloaded_archive_s_sha256_does_not_match_t')
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
        raise ChimeraRuntimeError('err.selfupdate.could_not_extract_the_update_archive', p0=e) from e
    exe = next(dest.rglob(EXE_NAME), None)
    if exe is None:
        raise ChimeraRuntimeError('err.selfupdate.the_update_archive_does_not_contain', p0=EXE_NAME)
    return exe.parent


# --- установка --------------------------------------------------------------------

def _q(p) -> str:
    return f'"{p}"'


def _files(root: Path) -> list[str]:
    """Файлы под root — относительными путями через «/», без самого манифеста."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name != MANIFEST)


def write_manifest(root: Path) -> list[str]:
    """Пишет root/manifest.txt — список файлов релиза (зовётся при сборке)."""
    files = _files(root)
    (root / MANIFEST).write_text("\n".join(files) + "\n", encoding="utf-8", newline="\n")
    return files


def read_manifest(root: Path) -> set[str] | None:
    try:
        text = (root / MANIFEST).read_text(encoding="utf-8")
    except OSError:
        return None
    return {line.strip() for line in text.splitlines() if line.strip()}


def _backup(app_dir: Path, files: set[str], rollback: Path) -> None:
    """Копия текущей версии для отката — только своих файлов, пока программа жива."""
    if rollback.exists():
        shutil.rmtree(rollback)
    try:
        for rel in sorted(files | {MANIFEST}):
            src = app_dir / rel
            if src.is_file():
                dst = rollback / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    except OSError as e:
        raise ChimeraRuntimeError('err.selfupdate.could_not_save_the_current_version_for_rollback', p0=e) from e


def _win(root: str, rel: str) -> str:
    return str(Path(root) / rel.replace("/", "\\"))


def write_script(app_dir: Path, staged: Path, pid: int, restart_service: bool, relaunch: bool,
                 script: Path, log: Path, rollback: Path) -> Path:
    """Сохраняет текущую версию в rollback и пишет apply.cmd: дождаться выхода pid,
    положить новую версию, убрать файлы, которых в ней нет, при ошибке — вернуть старую.

    RuntimeError — ставить нельзя (нет manifest.txt, копия для отката не
    получилась); программа при этом ещё работает и ничего не тронуто.
    """
    old = read_manifest(app_dir)
    if old is None:
        raise ChimeraRuntimeError('err.selfupdate.the_application_folder_has_no_so_its_files_canno', p0=MANIFEST)
    keep = set(KEEP_FILES) | {MANIFEST}
    new = set(_files(staged))
    # в пользовательских папках ничего не удаляем — ни при обновлении, ни при откате
    stale = sorted(f for f in old - new - keep if not _in_user_dir(f))  # были в прошлой версии, в новой нет
    added = sorted(f for f in new - old - keep if not _in_user_dir(f))  # появятся с новой — при откате убрать
    _backup(app_dir, old, rollback)

    app, st, rb, lg = (str(Path(p)) for p in (app_dir, staged, rollback, log))
    # настройки пользователя не перезаписывать, даже если релиз вдруг принёс файл с тем же путём
    xf = " ".join(_q(_win(st, f)) for f in KEEP_FILES)
    xd = " ".join(_q(_win(st, d)) for d in USER_DIRS)
    # /E без /MIR — копировать, ничего не удаляя; /R:2 /W:1 — занятый файл не ждать
    # по умолчанию «миллион раз по 30 с»; /NP /NJH /NJS — лог короче
    rc = "/E /R:2 /W:1 /NP /NJH /NJS"
    # /IS /IT — копировать и «одинаковые» файлы: robocopy сравнивает только размер и
    # время, и файл новой версии того же размера с той же датой иначе остался бы старым
    # /IM — отдельный класс NTFS Modified: ChangeTime может отличаться при том же mtime.
    force = "/IS /IT /IM"
    # пользовательские папки — отдельным проходом: /XC /XN /XO пропускают всё, что уже
    # лежит у пользователя, и копируют только новые файлы релиза
    user_dirs = [f'robocopy {_q(_win(st, d))} {_q(_win(app, d))} /XC /XN /XO {rc} >>"%LOG%"' + "\r\n"
                 + "if errorlevel 8 goto rollback" for d in USER_DIRS if (Path(st) / d).is_dir()]
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
        'echo [%date% %time%] программа закрыта, ставлю новую версию>>"%LOG%"',
        f'robocopy {_q(st)} {_q(app)} /XF {xf} /XD {xd} {force} {rc} >>"%LOG%"',
        "if errorlevel 8 goto rollback",
        *user_dirs,
        *(f'del /F /Q {_q(_win(app, rel))} >nul 2>&1' for rel in stale),
        'echo [%date% %time%] готово>>"%LOG%"',
        f'rmdir /S /Q {_q(Path(st).parent)} >nul 2>&1',
        "set RESULT=0",
        "goto after",
        ":rollback",
        'echo [%date% %time%] ошибка копирования — откат на прежнюю версию>>"%LOG%"',
        f'robocopy {_q(rb)} {_q(app)} {force} {rc} >>"%LOG%"',
        *(f'del /F /Q {_q(_win(app, rel))} >nul 2>&1' for rel in added),
        "set RESULT=2",
        ":after",
    ]
    if restart_service:
        lines.append(f'schtasks /Run /TN "{SERVICE_TASK}" >>"%LOG%" 2>&1')
    if relaunch:
        # --window: без аргументов exe из консоли печатает справку (modules/cli/entry.py)
        lines.append(f'start "" {_q(Path(app) / EXE_NAME)} --window')
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
