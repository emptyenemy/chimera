"""Telegram-прокси — интеграция flowseal/tg-ws-proxy.

Ядро (пакет `proxy`) импортируется прямо из сабмодуля upstream/tg-ws-proxy
и крутится в фоновом потоке со своим asyncio-циклом — трей и окна апстрима
не используются. Обновление прокси = обновление сабмодуля:

    git submodule update --remote upstream/tg-ws-proxy

Настройки (host/port/secret/autostart) — в state.json рядом с модулем.
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraRuntimeError, ChimeraValueError

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

DEFAULTS = {
    "host": "127.0.0.1", "port": 1443, "secret": "", "autostart": False,
    # «продвинутые» настройки ядра (proxy.config.ProxyConfig) — дефолты 1:1 с апстримом,
    # старые state.json без этих ключей просто дополняются дефолтами при загрузке.
    "disable_secure": False,           # --no-secure: порт 80 для CF-proxy/worker
    "fallback_cfproxy": True,          # --no-cfproxy инвертирован
    "cfproxy_user_domains": [],        # --cfproxy-domain (свои CF-домены вместо авто-пула)
    "cfproxy_worker_domains": [],      # --cfproxy-worker-domain
    "fake_tls_domain": "",             # --fake-tls-domain: включает ee-secret маскировку
    "dc_redirects": {"2": "149.154.167.220", "4": "149.154.167.220"},  # --dc-ip DC:IP
    "proxy_protocol": False,           # --proxy-protocol (за nginx/haproxy)
    "force_test_dc": False,            # --force-test-dc
}

_SECRET_RE = re.compile(r"^[0-9a-f]{32}$")
_ADV_BOOL_KEYS = ("disable_secure", "fallback_cfproxy", "proxy_protocol", "force_test_dc")


def _validate_domain(domain) -> str:
    """Правила — как у апстрима (proxy/config.py:_is_valid_domain): точечные метки,
    буквы/цифры/дефис без дефиса по краям, TLD от 2 символов с буквой."""
    d = str(domain).strip().lower()
    if not d or len(d) > 253 or d.startswith(".") or d.endswith("."):
        raise ChimeraValueError('err.tgproxy.manager.invalid_domain', p0=f'{domain!r}')
    labels = d.split(".")
    if len(labels) < 2:
        raise ChimeraValueError('err.tgproxy.manager.invalid_domain', p0=f'{domain!r}')
    for label in labels:
        if not label or len(label) > 63 or label[0] == "-" or label[-1] == "-":
            raise ChimeraValueError('err.tgproxy.manager.invalid_domain', p0=f'{domain!r}')
        if not all(ch.isalnum() or ch == "-" for ch in label):
            raise ChimeraValueError('err.tgproxy.manager.invalid_domain', p0=f'{domain!r}')
    tld = labels[-1]
    if len(tld) < 2 or not any(ch.isalpha() for ch in tld):
        raise ChimeraValueError('err.tgproxy.manager.invalid_domain', p0=f'{domain!r}')
    return d


def _normalize_domains(value) -> list:
    """Строка/список доменов -> список валидных, без дублей, как coerce_domain_list
    + _normalize_domain_pool апстрима (запятая/точка с запятой/пробел — разделители)."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ChimeraValueError('err.tgproxy.manager.domain_lists_must_be_a_string_or_a_list_of_strin')
    seen = set()
    out = []
    for raw in items:
        for part in str(raw).replace(",", " ").replace(";", " ").split():
            d = _validate_domain(part)
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out


def _validate_dc_redirects(value) -> dict:
    """{dc: ip} -> {str(dc): ip}, как parse_dc_ip_list апстрима (--dc-ip DC:IP),
    но на входе уже разобранный объект, а не список "DC:IP" строк."""
    if not isinstance(value, dict):
        raise ChimeraValueError('err.tgproxy.manager.dc_redirects_must_be_an_object_mapping_dc_number')
    result = {}
    for dc_raw, ip_raw in value.items():
        try:
            dc_n = int(dc_raw)
        except (TypeError, ValueError):
            raise ChimeraValueError('err.tgproxy.manager.invalid_dc_number', p0=f'{dc_raw!r}') from None
        try:
            socket.inet_pton(socket.AF_INET, str(ip_raw))
        except OSError:
            raise ChimeraValueError('err.tgproxy.manager.invalid_ip_for_dc', p0=dc_n, p1=f'{ip_raw!r}') from None
        result[str(dc_n)] = str(ip_raw)
    return result


def _import_core():
    """Подцепляет пакет proxy из сабмодуля. У сабмодуля есть свои ui/ и utils/,
    поэтому путь добавляется в КОНЕЦ sys.path — наши одноимённые пакеты в приоритете."""
    if not (UPSTREAM / "proxy" / "__init__.py").exists():
        raise ChimeraRuntimeError('err.tgproxy.manager.the_tg_ws_proxy_submodule_is_missing_run_git_sub')
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
        raise ChimeraValueError('err.tgproxy.manager.the_secret_must_contain_32_hex_characters_or_34')
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

    def restore_config(self, config: dict) -> dict:
        from modules.configbackups import normalize
        target = normalize("telegram", config)
        running = self.running
        self.config = target
        self._save()
        if running:
            self.restart()
        return self.state()

    def set_config(self, host: str, port, secret: str, autostart: bool) -> dict:
        host = str(host).strip() or "127.0.0.1"
        port = int(port)
        if not 1 <= port <= 65535:
            raise ChimeraValueError('err.tgproxy.manager.the_port_must_be_a_number_from_1_to_65535')
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

    def set_advanced(self, options: dict) -> dict:
        """«Продвинутые» настройки ядра (CF-proxy/worker домены, Fake TLS, dc-ip, ...).
        Валидирует и сохраняет только переданные ключи — остальные не трогает. Ядро
        читает proxy_config один раз при старте (см. _apply_config), поэтому на уже
        запущенный прокси эффекта нет — restart_required в ответе подсказывает, что
        нужен перезапуск (tg_stop/tg_start), сама его не перезапускает."""
        if not isinstance(options, dict):
            raise ChimeraValueError('err.tgproxy.manager.options_must_be_a_settings_object')
        updates = {}
        for key in _ADV_BOOL_KEYS:
            if key in options:
                updates[key] = bool(options[key])
        if "cfproxy_user_domains" in options:
            updates["cfproxy_user_domains"] = _normalize_domains(options["cfproxy_user_domains"])
        if "cfproxy_worker_domains" in options:
            updates["cfproxy_worker_domains"] = _normalize_domains(options["cfproxy_worker_domains"])
        if "fake_tls_domain" in options:
            raw = options["fake_tls_domain"]
            updates["fake_tls_domain"] = _validate_domain(raw) if str(raw or "").strip() else ""
        if "dc_redirects" in options:
            updates["dc_redirects"] = _validate_dc_redirects(options["dc_redirects"])
        self.config.update(updates)
        self._save()
        result = self.state()
        result["restart_required"] = self.running
        return result

    def _apply_config(self, core) -> None:
        pc = core.proxy_config
        pc.host = self.config["host"]
        pc.port = self.config["port"]
        pc.secret = self.config["secret"]
        pc.disable_secure = bool(self.config.get("disable_secure", False))
        pc.fallback_cfproxy = bool(self.config.get("fallback_cfproxy", True))
        pc.cfproxy_user_domains = list(self.config.get("cfproxy_user_domains") or [])
        pc.cfproxy_worker_domains = list(self.config.get("cfproxy_worker_domains") or [])
        pc.fake_tls_domain = str(self.config.get("fake_tls_domain") or "")
        pc.proxy_protocol = bool(self.config.get("proxy_protocol", False))
        pc.force_test_dc = bool(self.config.get("force_test_dc", False))
        pc.dc_redirects = {int(dc): ip for dc, ip in (self.config.get("dc_redirects") or {}).items()}

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
                self._error = (_tr('msg.modules.tgproxy.manager.port_is_occupied_by_another_application_change_t', p0=f"{self.config['port']}"))
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
                raise RuntimeError(self._error or _tr('msg.modules.tgproxy.manager.proxy_could_not_start'))
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
            ftls = self.config.get("fake_tls_domain") or ""
            if ftls:
                # ee-secret: следом за секретом hex самого домена маскировки (Fake TLS) —
                # так же, как апстрим строит ee_link в _run()
                domain_hex = ftls.encode("ascii").hex()
                link = (f"tg://proxy?server={link_host}&port={self.config['port']}"
                        f"&secret=ee{self.config['secret']}{domain_hex}")
            else:
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
