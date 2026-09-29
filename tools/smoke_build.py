"""Дымовой тест собранной программы — «как у пользователя, начисто».

    python tools/smoke_build.py [папка сборки] [--full] [--flavor qt|webview|lite]
                                          (по умолчанию build\\Chimera, Qt)

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
import secrets
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


def _cli_step(app: Path, env: dict, name: str, args: list[str], check=None) -> dict:
    """Один вызов командной строки собранного exe. Вывод читаем через трубу: так проверяется,
    что режим консоли attach отдаёт текст, когда терминала нет, а stdout перенаправлен."""
    label = f"командная строка: {name}"
    try:
        r = subprocess.run([str(app / "Chimera.exe"), *args], cwd=app, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return {"name": label, "ok": False, "detail": str(e)}
    out = (r.stdout or r.stderr).strip()
    ok = r.returncode == 0 and bool(out) and (check is None or check(out))
    return {"name": label, "ok": ok, "detail": out.splitlines()[0][:120] if out else f"код {r.returncode}, вывода нет"}


def _json_ok(text: str) -> bool:
    try:
        return json.loads(text).get("ok") is True
    except ValueError:
        return False


def _cli_checks_while_running(app: Path, env: dict) -> list[dict]:
    """Пока окно работает: команды идут в него по каналу управления — сквозная проверка."""
    return [
        _cli_step(app, env, "--version", ["--version"], lambda t: "Chimera" in t),
        _cli_step(app, env, "agent-info --json", ["agent-info", "--json"], _json_ok),
        _cli_step(app, env, "status --json (через канал)", ["status", "--json"], _json_ok),
        _cli_step(app, env, "winws state --json (через канал)", ["winws", "state", "--json"], _json_ok),
        _cli_step(app, env, "lists show --json", ["lists", "show", "--json"], _json_ok),
    ]


def _cli_check(app: Path, env: dict) -> dict:
    """`Chimera.exe service status` — тот путь main.py, которым ставится и управляется фоновая служба."""
    return _cli_step(app, env, "service status", ["service", "status"])


def run(build: Path, full: bool = False, front: str = "next", flavor: str = "qt") -> int:
    if not (build / "Chimera.exe").exists():
        print(f"нет {build / 'Chimera.exe'} — сначала build.bat")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="chimera-smoke-"))
    app, data = tmp / "Chimera", tmp / "data"
    shutil.copytree(build, app, ignore=shutil.ignore_patterns("data", "config.json"))
    # единственное отличие от чистой установки: без UAC — иначе запрос прав на экране
    # (у exe манифеста администратора нет, но окно повышается само; auto_elevate=false это отключает)
    # Изолированные настройки: автоматические системные действия отключены.
    port = _free_port()
    config = {"auto_elevate": False, "frontend": front, "ui_port": port, "update_check": False}
    (app / "config.json").write_text(json.dumps(config), encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "QT_QPA_PLATFORM": "offscreen",             # никакого окна на экране
        "QTWEBENGINE_REMOTE_DEBUGGING": str(port),
        "CHIMERA_DATA": str(data),
        "CHIMERA_SMOKE": "1",
        "CHIMERA_INSTANCE_EVENT": rf"Local\Chimera_Smoke_{os.getpid()}",
    })
    token = secrets.token_urlsafe(24)
    if flavor != "qt":
        env.update({"CHIMERA_NO_BROWSER": "1", "CHIMERA_HTTP_TOKEN": token})
    log = open(tmp / "engine.log", "wb")
    # --window: exe без аргументов из консоли печатает справку, а окно нужно именно оно
    proc = subprocess.Popen([str(app / "Chimera.exe"), "--window" if flavor == "qt" else "--browser"], cwd=app, env=env, stdout=log,
                            stderr=subprocess.STDOUT)
    try:
        if flavor == "qt":
            _wait_cdp(port, proc)
            command = ["node", str(CDP), str(port), str(CHECKS)]
        else:
            from tools.ui_preview import _browser
            browser = _browser()
            if not browser:
                raise RuntimeError("Headless Edge/Chrome is required")
            deadline = time.monotonic() + 60
            while True:
                try:
                    request = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"X-Chimera-Token": token})
                    with urllib.request.urlopen(request, timeout=2):
                        break
                except OSError:
                    if proc.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("HTTP bridge did not start") from None
                    time.sleep(0.2)
            command = ["node", str(ROOT / "tools" / "smoke_http.mjs"), browser,
                       f"http://127.0.0.1:{port}/?t={token}", str(CHECKS)]
        r = subprocess.run([*command, *(["full"] if full else [])],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=420)
        if r.returncode != 0:
            print(r.stdout.replace(token, "<token>"), r.stderr.replace(token, "<token>"))
            return 1
        result = json.loads(r.stdout.strip().splitlines()[-1])
        result["steps"] += _cli_checks_while_running(app, env)
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
        print("---- хвост лога движка ----\n" + tail.replace(token, "<token>"))
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'всё работает' if not failed else f'сломано: {failed}'}")
    return 1 if failed else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    flavor = "qt"
    if "--flavor" in args:
        i = args.index("--flavor")
        flavor = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if flavor not in ("qt", "webview", "lite"):
        sys.exit("--flavor: qt, webview или lite")
    front = "next"
    if "--frontend" in args:
        i = args.index("--frontend")
        front = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if front not in ("next",):
        sys.exit("--frontend: next")
    args = [a for a in args if a != "--full"]
    sys.exit(run(Path(args[0]) if args else ROOT / "build" / "Chimera", full="--full" in sys.argv, front=front, flavor=flavor))
