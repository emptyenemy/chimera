"""Канал управления: локальный сервер, через который `chimera ...` говорит с работающей Chimera.

Живёт рядом с любым движком окна (PySide6, pywebview, браузер): движок после создания
Api зовёт start_for(api). Слушает только 127.0.0.1 на случайном порту. Порт и токен
пишутся в файл data/control.json (доступ только текущему пользователю) и убираются при
выходе; по этому файлу CLI находит запущенную программу.

Через канал доступен не весь Api, а явный набор ALLOWED_METHODS. Секреты (ссылка
прокси, секрет Telegram-прокси) в ответах скрыты, пока клиент прямо не попросил
показать. Защита от чужих страниц в браузере: токен в заголовке, проверка Host
(подмена DNS) и запрет Origin (запросы из страниц).

Сторожа «клиент пропал — выходим» здесь нет: он есть только у движка browser.
"""

from modules.i18n import t as _tr

import atexit
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from modules import paths
from modules.cli.registry import allowed_methods
from modules.version import VERSION

# Версия протокола CLI <-> приложение. Растёт только при несовместимых изменениях.
PROTOCOL = 1
HOST = "127.0.0.1"
TOKEN_HEADER = "X-Chimera-Token"
CONTROL_PATH = paths.data_path("control.json")

# Методы Api, доступные CLI, берутся из таблицы команд (modules/cli/registry.py): каждое
# действие интерфейса, у которого есть команда, доступно и по каналу. Остальное (подписки
# окна, открытие ссылок в браузере и т. п.) через канал недоступно.
ALLOWED_METHODS = allowed_methods()

# Настройки config.json, которые можно менять через CLI: ровно те, что меняет окно
# (Настройки: движок окна, автоповышение, трей, канал и проверка обновлений, тема, язык).
# Режим интерфейса (interface) и остальное — правкой config.json.
CONFIG_KEYS_WRITABLE = frozenset({
    "ui_backend", "auto_elevate", "close_to_tray", "update_channel", "update_check", "theme", "lang",
})

MAX_BODY = 1 << 20  # запросы CLI — доли килобайта; больше мегабайта — не наш клиент
SECRET_KEYS = frozenset({"link", "secret"})
CONTROL_ACTIONS = frozenset({"quit", "restart"})


# --- секреты ------------------------------------------------------------------------

def _mask(value: str) -> str:
    if not value:
        return value
    scheme = re.match(r"^([a-zA-Z][\w+.-]*://)", value)
    return (scheme.group(1) if scheme else "") + _tr('msg.modules.control.hidden')


def redact(obj):
    """Копия структуры, где значения секретных ключей заменены на маску."""
    if isinstance(obj, dict):
        return {k: (_mask(v) if k in SECRET_KEYS and isinstance(v, str) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


# --- файл со связью -----------------------------------------------------------------

def _restrict_permissions(path: Path) -> None:
    """Файл с токеном читает только текущий пользователь (и повышенная копия того же пользователя)."""
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return
    # по имени icacls разбирает учётную запись неверно (ACL выходит с пустым именем и
    # файл нельзя даже переименовать), поэтому — по SID текущего пользователя
    sid = _current_sid()
    if not sid:
        return  # не узнали, кто мы: остаются права папки data/, лучше так, чем закрыть файл от всех
    try:
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"],
                       capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def _current_sid() -> str | None:
    try:
        out = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return out.strip().split(",")[-1].strip('"') or None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def write_discovery(port: int, token: str, *, interactive_sid=None) -> Path:
    data = {"port": port, "token": token, "pid": os.getpid(), "protocol": PROTOCOL,
            "version": VERSION, "started": int(time.time())}
    path = CONTROL_PATH
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    _restrict_permissions(tmp)
    if _current_sid() == "S-1-5-18":
        _grant_service_user(tmp, sid=interactive_sid, force=True)
    os.replace(tmp, path)
    return path


def read_discovery() -> dict | None:
    try:
        data = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not {"port", "token"} <= data.keys():
        return None
    return data


def remove_discovery(only_pid: int | None = None) -> None:
    """Убирает файл. С only_pid — только если запись наша (её мог перезаписать другой экземпляр)."""
    if only_pid is not None:
        info = read_discovery()
        if info is None or info.get("pid") != only_pid:
            return
    try:
        CONTROL_PATH.unlink()
    except OSError:
        pass


# --- перезапуск ---------------------------------------------------------------------

def relaunch_command() -> list[str]:
    """Как запустить окно заново: собранный exe напрямую, из исходников — main.py."""
    if paths.IS_FROZEN:
        return [sys.executable, "--window"]
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else exe), str(Path(__file__).parent.parent / "main.py"), "--window"]


def spawn_relaunch(service_mode: bool = False) -> None:
    """Запускает новую копию после выхода этой: пауза, потом start. Новая копия стартует,
    когда событие «одного экземпляра» уже освобождено (см. modules/instance.py)."""
    if sys.platform != "win32":
        return
    args = relaunch_command()
    if service_mode:
        args = [*args[:-1], "service", "run"]
    cmd = subprocess.list2cmdline(args)
    subprocess.Popen(["cmd", "/c", f'ping -n 4 127.0.0.1 >nul & start "" {cmd}'],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                     | getattr(subprocess, "DETACHED_PROCESS", 0),
                     close_fds=True)


# --- сервер -------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Chimera"

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass  # клиент ушёл, не дождавшись ответа

    def _refuse(self) -> None:
        self._send(403, {"ok": False, "code": "forbidden", "error": _tr('msg.modules.control.access_denied')})

    def _guard(self) -> bool:
        """Токен, Host и Origin. False — ответ уже отправлен."""
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._refuse()
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            self._refuse()
            return False
        given = self.headers.get(TOKEN_HEADER) or ""
        if not secrets.compare_digest(given, self.server.token):
            self._refuse()
            return False
        return True

    def _read_raw(self) -> bytes:
        """Тело запроса читаем до любых проверок: при отказе оставшиеся байты испортили бы
        разбор следующего запроса на том же соединении."""
        try:
            size = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
        except ValueError:
            size = 0
        return self.rfile.read(size) if size > 0 else b""

    def _body(self, raw: bytes):
        try:
            req = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            req = None
        if not isinstance(req, dict):
            self._send(400, {"ok": False, "code": "bad_request", "error": _tr('msg.modules.control.malformed_request')})
            return None
        return req

    def do_GET(self):
        if not self._guard():
            return
        if self.path.split("?")[0] == "/hello":
            return self._send(200, {"protocol": PROTOCOL, "version": VERSION, "pid": os.getpid()})
        self._send(404, {"ok": False, "code": "not_found", "error": _tr('msg.modules.control.no_such_address')})

    def do_POST(self):
        raw = self._read_raw()
        if not self._guard():
            return
        path = self.path.split("?")[0]
        req = self._body(raw)
        if req is None:
            return
        if path == "/api":
            return self._api(req)
        if path == "/control":
            return self._control(req)
        self._send(404, {"ok": False, "code": "not_found", "error": _tr('msg.modules.control.no_such_address')})

    def _api(self, req: dict) -> None:
        method = req.get("method")
        args = req.get("args", [])
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return self._send(400, {"ok": False, "code": "bad_request", "error": _tr('msg.modules.control.malformed_arguments')})
        if not isinstance(method, str) or not isinstance(args, list):
            return self._send(400, {"ok": False, "code": "bad_request", "error": _tr('msg.modules.control.method_and_args_are_required')})
        if method not in self.server.allowed or method.startswith("_"):
            return self._send(200, {"ok": False, "code": "forbidden",
                                    "error": _tr('msg.modules.control.method_is_not_available_through_the_command_line', p0=f'{method!r}')})
        if method == "config_set" and (not args or args[0] not in CONFIG_KEYS_WRITABLE):
            return self._send(200, {"ok": False, "code": "forbidden",
                                    "error": _tr('msg.modules.control.this_setting_cannot_be_changed_through_the_comma')})
        result = json.loads(self.server.api.dispatch(method, json.dumps(args)))
        if not req.get("reveal"):
            result = redact(result)
        self._send(200, result)

    def _control(self, req: dict) -> None:
        action = req.get("action")
        if action not in CONTROL_ACTIONS:
            return self._send(400, {"ok": False, "code": "bad_request", "error": _tr('msg.modules.control.unknown_action')})
        self._send(200, {"ok": True, "data": {"action": action}})
        threading.Thread(target=self.server.finish, args=(action,), daemon=True).start()

    def log_message(self, fmt, *args):
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # клиент оборвал соединение (Ctrl+C у CLI, закрытая консоль) — не событие, шум в консоль не нужен
        if isinstance(sys.exc_info()[1], OSError):
            return
        super().handle_error(request, client_address)


class ControlServer:
    def __init__(self, api, allowed=ALLOWED_METHODS, port: int = 0):
        self.api = api
        self.allowed = allowed
        self.token = secrets.token_urlsafe(24)
        self._port = port
        self._httpd = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> ControlServer:
        httpd = _Server((HOST, self._port), _Handler)
        httpd.api, httpd.allowed, httpd.token, httpd.finish = self.api, self.allowed, self.token, self._finish
        self._httpd = httpd
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True, name="chimera-control").start()
        write_discovery(self.port, self.token)
        return self

    def stop(self) -> None:
        if self._httpd is None:
            return
        remove_discovery(only_pid=os.getpid())
        httpd, self._httpd = self._httpd, None
        httpd.shutdown()
        httpd.server_close()

    def _finish(self, action: str) -> None:
        """quit/restart: гасим модули и просим движок закрыть программу (как при обновлении)."""
        time.sleep(0.2)  # ответ клиенту уйдёт раньше, чем мы начнём закрываться
        if action == "restart":
            if getattr(self.api, "_service_owned", False):
                spawn_relaunch(service_mode=True)
            else:
                spawn_relaunch()
        self.api.shutdown()
        self.api.request_quit()


_service_access_sid: str | None = None
_service_access_check = 0.0


def _interactive_sid() -> str | None:
    script = ("$name = (Get-CimInstance Win32_ComputerSystem).UserName; "
              "if ($name) { ([System.Security.Principal.NTAccount]::new($name)).Translate("
              "[System.Security.Principal.SecurityIdentifier]).Value }")
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        sid = result.stdout.strip()
        return sid if re.fullmatch(r"S-1-5-21-(?:\d+-){3}\d+", sid) else None
    except (OSError, subprocess.SubprocessError):
        return None


def _grant_service_user(path: Path, *, sid=None, force=False) -> None:
    global _service_access_sid
    sid = sid or _interactive_sid()
    if not force and sid == _service_access_sid:
        return
    try:
        if _service_access_sid and (force or sid != _service_access_sid):
            removed = subprocess.run(["icacls", str(path), "/remove:g", f"*{_service_access_sid}"],
                                     capture_output=True, timeout=10,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if removed.returncode:
                return
        if sid:
            result = subprocess.run(["icacls", str(path), "/grant:r", f"*{sid}:R"],
                                    capture_output=True, timeout=10,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                return
        _service_access_sid = sid
    except (OSError, subprocess.SubprocessError):
        pass


def refresh_service_access() -> None:
    global _service_access_check
    if sys.platform != "win32" or time.monotonic() - _service_access_check < 10:
        return
    _service_access_check = time.monotonic()
    if _server is not None and _current_sid() == "S-1-5-18":
        sid = _interactive_sid()
        if sid != _service_access_sid:
            # После смены пользователя прежний токен больше не принимает сервер.
            _server.token = secrets.token_urlsafe(32)
            write_discovery(_server.port, _server.token, interactive_sid=sid)


_server: ControlServer | None = None


def start_for(api) -> ControlServer | None:
    """Поднимает канал для работающей программы; зовут движки окна после создания Api."""
    global _server
    if _server is not None:
        return _server
    try:
        _server = ControlServer(api).start()
    except Exception:  # noqa: BLE001 — канал вспомогательный: не вышел, программа работает и без командной строки
        return None
    atexit.register(_server.stop)
    return _server


def stop_current() -> None:
    """Закрывает канал и убирает файл со связью (при выходе программы)."""
    global _server
    server, _server = _server, None
    if server is not None:
        server.stop()
