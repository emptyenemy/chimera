"""Бэкенд окна Chromium: локальный HTTP-сервер и отдельный профиль браузера.

Третий вариант к PySide6 и pywebview (config.json -> "ui_backend": "browser").
Фронт отдаётся локальным сервером на 127.0.0.1 и открывается в отдельном
окне Edge/Chrome без адресной строки. Собственный профиль и группа процессов
не затрагивают окна браузера пользователя.

Мост тот же JSON-RPC, что у остальных движков, разложенный на два эндпоинта:
  • POST /api    — {method, args} -> Api.dispatch(...) (один вызов = один запрос);
  • GET /events  — long-poll очереди push'ей (чебурчек/блокчек/проверка источников),
                   то же самое, что evaluate_js у pywebview и сигнал у Qt.

Доступ закрыт одноразовым токеном: сервер слушает только петлю, но на локальной
машине к нему может постучаться любой процесс, а через этот мост доступно всё
API (hosts, DNS, запуск winws). Токен живёт в памяти процесса, выдаётся один раз
в адресе страницы и дальше ходит заголовком.

Закрытие собственного окна завершает сервер и модули. Headless-проверка
держит сервер long-poll запросами; без клиента дольше IDLE_TIMEOUT он завершается.
"""

from modules.i18n import t as _tr

import json
import os
import mimetypes
import secrets
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import frontend, theme
from .api import WEB_DIR, Api

HOST = "127.0.0.1"
DEFAULT_PORT = 0        # 0 — свободный порт от ОС (адрес всё равно открываем сами)
POLL_TIMEOUT = 25.0     # сколько держим /events открытым, если событий нет
IDLE_TIMEOUT = 90.0     # столько живём без единого запроса страницы, потом выходим
TOKEN_HEADER = "X-Chimera-Token"
COOKIE_NAME = "chimera_token"

# что вообще разрешено отдать из ui/web — на всякий случай, хотя каталог наш
_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".woff2": "font/woff2",
          ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
          ".json": "application/json; charset=utf-8"}


def _mark_page(html: bytes, token: str, mode: str = "dark", *, native=False) -> bytes:
    """Помечает страницу как «отдана нами» и кладёт туда токен.

    Фронт не может опознать движок по протоколу: pywebview тоже поднимает свой
    http-сервер для локальных файлов, так что http:// сам по себе ничего не
    значит (см. initBridge в ui/web/js/core.js). Маркер снимает эту двусмысленность,
    а токен заодно уезжает из адресной строки в скрипт. Туда же — класс темы на <html>:
    скрипт стоит в <head>, то есть исполняется до первой отрисовки (ui/theme.py).
    """
    marker = "" if native else f"window.__CHIMERA_HTTP__=true;window.__CHIMERA_TOKEN__={json.dumps(token)};"
    tag = f"<script>{marker}{theme.boot_script(mode)}</script>".encode()
    return html.replace(b"</head>", tag + b"\n</head>", 1) if b"</head>" in html else tag + html


class _Hub:
    """Очередь push-событий для long-poll: у страницы курсор, у нас — хвост."""

    def __init__(self):
        self._cv = threading.Condition()
        self._events = deque(maxlen=1000)
        self._seq = 0
        self.connected = threading.Event()
        self.touched = time.monotonic()  # когда страница в последний раз давала о себе знать

    def push(self, fn: str, payload) -> None:
        with self._cv:
            self._seq += 1
            self._events.append((self._seq, fn, payload))
            self._cv.notify_all()

    def poll(self, cursor: int, timeout: float) -> tuple[list, int]:
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                out = [{"fn": fn, "payload": p} for seq, fn, p in self._events if seq > cursor]
                left = deadline - time.monotonic()
                if out or left <= 0:
                    return out, self._seq
                self._cv.wait(min(1.0, left))

    def touch(self) -> None:
        self.touched = time.monotonic()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # long-poll без keep-alive — это новый коннект на каждое событие
    server_version = "CHIMERA"

    # у сервера в атрибутах: api, hub, token (ставятся в run())
    def _authorized(self, query: dict) -> bool:
        """Токен из заголовка (запросы фронта), адреса (первая загрузка) или cookie.

        Cookie нужна не для красоты: css/js/шрифты браузер тянет сам, ни заголовка,
        ни ?t он к ним не добавит — без неё страница приезжает голой.
        """
        cookie = ""
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                cookie = value
        given = self.headers.get(TOKEN_HEADER) or (query.get("t") or [""])[0] or cookie
        return secrets.compare_digest(given, self.server.token)

    def _send(self, code: int, body: bytes, ctype: str, set_cookie: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie",
                             f"{COOKIE_NAME}={self.server.token}; Path=/; SameSite=Strict; HttpOnly")
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionError:
            pass  # вкладку закрыли на середине long-poll — обычное дело (на Windows это ConnectionAbortedError)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorized(query):
            return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        self.server.hub.touch()

        if url.path == "/events":
            try:
                cursor = int((query.get("since") or ["0"])[0])
            except ValueError:
                cursor = 0
            events, seq = self.server.hub.poll(cursor, POLL_TIMEOUT)
            return self._json({"events": events, "seq": seq})

        # каталог фронта задаёт run(); выбран новый без сборки — вместо страницы подсказка
        web_dir = getattr(self.server, "web_dir", None) or WEB_DIR
        if getattr(self.server, "missing_next", False) and url.path in ("/", ""):
            return self._send(200, frontend.missing_page(), "text/html; charset=utf-8")
        rel = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
        path = (web_dir / rel).resolve()
        if not path.is_file() or web_dir.resolve() not in path.parents:
            if url.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")  # своей иконки нет — молча, без 404 в консоли
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype = _TYPES.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] \
            or "application/octet-stream"
        body = path.read_bytes()
        if path.name == "index.html":
            self.server.hub.connected.set()
            body = _mark_page(body, self.server.token, theme.resolve_theme(), native=getattr(self.server, "native_bridge", False))
            # cookie ставим на самой странице — дальше с ней ходят и статика, и мост
            return self._send(200, body, ctype, set_cookie=True)
        self._send(200, body, ctype)

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorized(parse_qs(url.query)):
            return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        self.server.hub.touch()
        if url.path != "/api":
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            req = json.loads(raw.decode("utf-8"))
            method, args_json = req["method"], req.get("args") or "[]"
        except (ValueError, KeyError, TypeError):
            return self._json({"ok": False, "error": _tr('msg.ui.backend_browser.malformed_request')}, 400)
        # dispatch сам ловит ошибки метода и возвращает готовый JSON-текст
        body = self.server.api.dispatch(method, args_json).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        pass  # свой лог не ведём: страница одна, а шума от long-poll много


def _watchdog(server, api: Api, hub: _Hub, stop: threading.Event, browser=None) -> None:
    """Нет запросов дольше IDLE_TIMEOUT — вкладку закрыли, гасимся как по закрытию окна."""
    while not stop.wait(5.0):
        if (browser is not None and not browser.running()) or time.monotonic() - hub.touched > IDLE_TIMEOUT:
            print(_tr('msg.ui.backend_browser.tab_closed_stopping_chimera'))
            api.shutdown()
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


def run():
    api = Api()
    try:
        _run_server(api)
    finally:
        api.shutdown()


def _run_server(api):
    from modules import appconfig, control

    hub = _Hub()
    api.push = hub.push
    control.start_for(api)  # канал для `chimera ...` (modules/control.py)

    port = int(appconfig.load().get("ui_port") or DEFAULT_PORT)
    server = ThreadingHTTPServer((HOST, port), _Handler)
    server.daemon_threads = True
    headless = os.environ.get("CHIMERA_NO_BROWSER") == "1"
    token = os.environ.get("CHIMERA_HTTP_TOKEN") if headless else None
    server.api, server.hub, server.token = api, hub, token or secrets.token_urlsafe(24)
    server.missing_next = frontend.next_missing()
    server.web_dir = frontend.NEXT_DIR
    if server.missing_next:
        print(frontend.MISSING_TEXT)

    url = f"http://{HOST}:{server.server_address[1]}/?t={server.token}"
    if not headless:
        print(_tr('msg.ui.backend_browser.chimera_is_open_in_the_browser_close_the_tab_or', p0=f'{url}'))
    stop = threading.Event()

    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    listener = browser = None
    api.request_quit = server.shutdown
    try:
        if not headless:
            unavailable = os.environ.get("CHIMERA_SMOKE") == "1" and os.environ.get("CHIMERA_SMOKE_NO_BROWSER") == "1"
            if unavailable:
                raise RuntimeError("No browser is available")
            from ui.browser_window import BrowserWindow
            browser = BrowserWindow(url)
            api.window_pids = browser.pids
            if not hub.connected.wait(12):
                raise RuntimeError("The browser did not open the interface")
            from modules import instance
            listener = instance.listen(browser.show)
        threading.Thread(target=_watchdog, args=(server, api, hub, stop, browser), daemon=True).start()
        while worker.is_alive():
            worker.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if listener:
            listener.close()
        if browser:
            browser.close()
        server.shutdown()
        server.server_close()
        api.shutdown()
