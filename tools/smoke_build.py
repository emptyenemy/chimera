"""Дымовой тест собранной программы — «как у пользователя, начисто».

    python tools/smoke_build.py [папка сборки] [--full]      (по умолчанию build\\Chimera)

--full — ещё и то, что требует прав администратора и меняет систему (запуск winws2,
запись hosts, прокси в PAC и TUN, смена DNS, задача автозапуска). Каждый шаг
возвращает как было, но запускать только в CI или на одноразовой машине.

Копирует сборку во временную папку без data/ и config.json, запускает Chimera.exe
без окна (Qt offscreen) и без запроса прав, подключается к встроенному Chromium по
CDP и прогоняет tools/smoke_checks.js — те же вызовы api(), что делает интерфейс:
стратегии и fake-блобы, ядро sing-box и разбор ссылки, запуск Telegram-прокси,
hosts и Flowseal, DNS, списки, версии, самообновление. Тесты исходников сборку не
видят; отсюда ловится то, что Nuitka не положила в exe.

Ничего не меняет в системе и не мешает открытой программе: своя копия, своя папка
данных (CHIMERA_DATA), своё имя защиты от второго экземпляра (CHIMERA_INSTANCE_EVENT),
свой порт Telegram-прокси. Проверки с пометкой «сеть» при отсутствии интернета не
валят тест. Код выхода 0 — всё работает.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKS = ROOT / "tools" / "smoke_checks.js"
CDP = ROOT / "tools" / "smoke_build.mjs"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_cdp(port: int, proc: subprocess.Popen, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Chimera.exe завершилась сама, код {proc.returncode}")
        try:
            pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read())
            if any(p.get("type") == "page" and p.get("url", "").endswith("index.html") for p in pages):
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("страница программы не поднялась за минуту")


def _cli_check(app: Path, env: dict) -> dict:
    """Командная строка собранного exe: `Chimera.exe service status` — тот путь main.py,
    которым ставится и управляется фоновая служба."""
    try:
        r = subprocess.run([str(app / "Chimera.exe"), "service", "status"], cwd=app, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        ok = r.returncode == 0
        return {"name": "командная строка: service status", "ok": ok,
                "detail": (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else f"код {r.returncode}"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"name": "командная строка: service status", "ok": False, "detail": str(e)}


def run(build: Path, full: bool = False) -> int:
    if not (build / "Chimera.exe").exists():
        print(f"нет {build / 'Chimera.exe'} — сначала build.bat")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="chimera-smoke-"))
    app, data = tmp / "Chimera", tmp / "data"
    shutil.copytree(build, app, ignore=shutil.ignore_patterns("data", "config.json"))
    # единственное отличие от чистой установки: без UAC — иначе запрос прав на экране
    (app / "config.json").write_text(json.dumps({"auto_elevate": False}), encoding="utf-8")

    port = _free_port()
    env = dict(os.environ)
    env.update({
        "__COMPAT_LAYER": "RunAsInvoker",           # манифест просит админа — запускаем как есть
        "QT_QPA_PLATFORM": "offscreen",             # никакого окна на экране
        "QTWEBENGINE_REMOTE_DEBUGGING": str(port),
        "CHIMERA_DATA": str(data),
        "CHIMERA_INSTANCE_EVENT": rf"Local\Chimera_Smoke_{os.getpid()}",
    })
    log = open(tmp / "engine.log", "wb")
    proc = subprocess.Popen([str(app / "Chimera.exe")], cwd=app, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        _wait_cdp(port, proc)
        r = subprocess.run(["node", str(CDP), str(port), str(CHECKS), *(["full"] if full else [])],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=420)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            return 1
        result = json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        log.close()
    result["steps"].append(_cli_check(app, env))

    failed = 0
    for s in result["steps"]:
        mark = "OK  " if s["ok"] else ("СЕТЬ" if s.get("network") else "FAIL")
        print(f"{mark}  {s['name']}{' — ' + s['detail'] if s['detail'] else ''}")
        failed += not s["ok"] and not s.get("network")
    for e in result["pageErrors"]:
        print(f"FAIL  ошибка на странице — {e}")
        failed += 1
    if failed:
        tail = (tmp / "engine.log").read_bytes()[-3000:].decode("utf-8", "replace")
        print("---- хвост лога движка ----\n" + tail)
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'всё работает' if not failed else f'сломано: {failed}'}")
    return 1 if failed else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--full"]
    sys.exit(run(Path(args[0]) if args else ROOT / "build" / "Chimera", full="--full" in sys.argv))
