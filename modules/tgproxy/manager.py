"""Telegram-прокси — интеграция flowseal/tg-ws-proxy.

Ядро (пакет `proxy`) импортируется прямо из сабмодуля upstream/tg-ws-proxy
и крутится в фоновом потоке со своим asyncio-циклом — трей и окна апстрима
не используются. Обновление прокси = обновление сабмодуля:

    git submodule update --remote upstream/tg-ws-proxy

Настройки (host/port/secret/autostart) — в state.json рядом с модулем.
"""

import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .. import paths

UPSTREAM = Path(__file__).parent.parent.parent / "upstream" / "tg-ws-proxy"
STATE_PATH = paths.data_path("tgproxy.json")
paths.migrate(Path(__file__).parent / "state.json", STATE_PATH)  # разовый перенос со старого места
LOG_PATH = paths.log_path("tgproxy.log")
paths.migrate(Path(__file__).parent / "tgproxy.log", LOG_PATH)
# ядро tg-ws-proxy логирует в этот логгер (см. proxy/*.py: getLogger('tg-mtproto-proxy'))
_CORE_LOGGER = "tg-mtproto-proxy"
RELEASES_API = "https://api.github.com/repos/Flowseal/tg-ws-proxy/releases/latest"
RELEASES_PAGE = "https://github.com/Flowseal/tg-ws-proxy/releases"

DEFAULTS = {"host": "127.0.0.1", "port": 1443, "secret": "", "autostart": False}

_SECRET_RE = re.compile(r"^[0-9a-f]{32}$")


def _import_core():
    """Подцепляет пакет proxy из сабмодуля. У сабмодуля есть свои ui/ и utils/,
    поэтому путь добавляется в КОНЕЦ sys.path — наши одноимённые пакеты в приоритете."""
    if not (UPSTREAM / "proxy" / "__init__.py").exists():
        raise RuntimeError(
            "Сабмодуль tg-ws-proxy не подтянут. Выполни: "
            "git submodule update --init upstream/tg-ws-proxy"
        )
    if str(UPSTREAM) not in sys.path:
        sys.path.append(str(UPSTREAM))
    import proxy  # noqa: F401  (пакет из сабмодуля)
    return proxy


def _new_secret() -> str:
    return os.urandom(16).hex()


def _normalize_secret(value: str) -> str:
    """32 hex-символа; ввод с префиксом dd/ee (как в tg-ссылке) тоже принимаем."""
    s = str(value).strip().lower()
    if len(s) == 34 and s[:2] in ("dd", "ee"):
        s = s[2:]
    if not _SECRET_RE.match(s):
        raise ValueError("Секрет — 32 hex-символа (или 34 с префиксом dd)")
    return s


class TgProxy:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._loop = None
        self._stop_event = None
        self._error: str | None = None
        self._log_handler: logging.Handler | None = None
        self.config = self._load()

    # --- конфиг --------------------------------------------------------------

    def _load(self) -> dict:
        data = dict(DEFAULTS)
        if STATE_PATH.exists():
            try:
                data.update(json.loads(STATE_PATH.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError):
                pass
        if not data["secret"]:
            data["secret"] = _new_secret()
            self._save(data)
        return data

    def _save(self, data: dict | None = None) -> None:
        STATE_PATH.write_text(
            json.dumps(data or self.config, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )

    def set_config(self, host: str, port, secret: str, autostart: bool) -> dict:
        host = str(host).strip() or "127.0.0.1"
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError("Порт — число от 1 до 65535")
        self.config.update({
            "host": host,
            "port": port,
            "secret": _normalize_secret(secret),
            "autostart": bool(autostart),
        })
        self._save()
        if self.running:
            self.restart()
        return self.state()

    def regen_secret(self) -> dict:
        self.config["secret"] = _new_secret()
        self._save()
        if self.running:
            self.restart()
        return self.state()

    # --- жизненный цикл --------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _apply_config(self, core) -> None:
        pc = core.proxy_config
        pc.host = self.config["host"]
        pc.port = self.config["port"]
        pc.secret = self.config["secret"]

    def _runner(self) -> None:
        import asyncio

        from proxy.tg_ws_proxy import _run

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop_event = asyncio.Event()
        try:
            loop.run_until_complete(_run(stop_event=self._stop_event))
        except Exception as exc:
            if "10048" in str(exc) or "Address already in use" in str(exc):
                self._error = (f"Порт {self.config['port']} уже занят другим "
                               "приложением — смени порт или закрой его.")
            else:
                self._error = str(exc)
        finally:
            # ядро не отменяет фоновые задачи warmup-пула при остановке —
            # гасим сами, иначе loop.close() сыплет "Task was destroyed"
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._loop = None
            self._stop_event = None

    # --- логи ядра -----------------------------------------------------------

    def _attach_log(self) -> None:
        """Перехватываем логгер ядра tg-ws-proxy в файл (свежий на каждый старт)."""
        self._detach_log()
        logger = logging.getLogger(_CORE_LOGGER)
        logger.setLevel(logging.INFO)
        try:
            h = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
        except OSError:
            return
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logger.addHandler(h)
        self._log_handler = h

    def _detach_log(self) -> None:
        if self._log_handler:
            logging.getLogger(_CORE_LOGGER).removeHandler(self._log_handler)
            try:
                self._log_handler.close()
            except OSError:
                pass
            self._log_handler = None

    def log_read(self, offset: int = 0) -> dict:
        """Инкрементальное чтение лога tg-прокси (живой стрим в UI)."""
        from modules import logutil
        return logutil.read_from(LOG_PATH, offset)

    def start(self) -> dict:
        if self.running:
            return self.state()
        core = _import_core()
        self._apply_config(core)
        self._error = None
        self._attach_log()
        self._thread = threading.Thread(target=self._runner, daemon=True, name="tg-proxy")
        self._thread.start()
        # ловим мгновенные ошибки старта (занятый порт и т.п.): ждём, пока ядро
        # поднимет сервер либо поток умрёт
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not self._thread.is_alive():
                self._thread = None
                raise RuntimeError(self._error or "Прокси не запустился")
            if self._server_up():
                break
            time.sleep(0.05)
        return self.state()

    def stop(self) -> dict:
        if self._loop and self._stop_event:
            loop, ev = self._loop, self._stop_event
            loop.call_soon_threadsafe(ev.set)
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._detach_log()
        return self.state()

    def restart(self) -> dict:
        self.stop()
        time.sleep(0.2)
        return self.start()

    def _server_up(self) -> bool:
        """Сервер ядра реально поднят. Смотрим на _server_instance апстрима —
        проверка порта не годится: его может слушать чужой процесс."""
        from proxy import tg_ws_proxy
        if hasattr(tg_ws_proxy, "_server_instance"):
            return tg_ws_proxy._server_instance is not None
        # если апстрим переименует поле — фолбэк на проверку порта
        host = self.config["host"]
        if host == "0.0.0.0":
            host = "127.0.0.1"
        try:
            with socket.create_connection((host, self.config["port"]), timeout=0.3):
                return True
        except OSError:
            return False

    # --- состояние для UI --------------------------------------------------------

    def state(self) -> dict:
        version = link = None
        try:
            core = _import_core()
            version = core.__version__
            link_host = core.get_link_host(self.config["host"]) or self.config["host"]
            link = (f"tg://proxy?server={link_host}&port={self.config['port']}"
                    f"&secret=dd{self.config['secret']}")
        except RuntimeError as e:
            self._error = str(e)
        return {
            **self.config,
            "running": self.running,
            "version": version,
            "link": link,
            "error": self._error,
        }

    def live_stats(self) -> dict:
        """Счётчики ядра — есть смысл только пока прокси запущен."""
        from proxy.stats import stats
        from proxy.utils import human_bytes

        return {
            "active": stats.connections_active,
            "total": stats.connections_total,
            "ws": stats.connections_ws,
            "tcp_fallback": stats.connections_tcp_fallback,
            "cfproxy": stats.connections_cfproxy,
            "up": human_bytes(stats.bytes_up),
            "down": human_bytes(stats.bytes_down),
        }

    # --- обновления ---------------------------------------------------------------

    def check_update(self) -> dict:
        """Сравнивает версию ядра в сабмодуле с последним релизом на GitHub."""
        current = _import_core().__version__
        req = urllib.request.Request(
            RELEASES_API, headers={"User-Agent": "chimera", "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest = str(data.get("tag_name", "")).lstrip("v")

        def ver(s):
            return tuple(int(x) for x in re.findall(r"\d+", s)[:3])

        has_update = bool(latest) and ver(latest) > ver(current)
        return {
            "current": current,
            "latest": latest or None,
            "has_update": has_update,
            "url": data.get("html_url") or RELEASES_PAGE,
        }
