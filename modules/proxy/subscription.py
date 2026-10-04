"""Подписка прокси: список серверов по ссылке провайдера и выбор самого быстрого.

Подписка — https-адрес, по которому провайдер отдаёт серверы: base64 со ссылкой на строку
(формат v2rayN), те же ссылки открытым текстом или JSON sing-box с outbounds. Каждая
ссылка проверяется тем же разбором, что и вставленная вручную; неподдерживаемые
пропускаются. Самый быстрый сервер — с наименьшей задержкой TCP-подключения к его порту.
У QUIC-протоколов (Hysteria, TUIC, WireGuard) TCP нет, они идут запасными: берутся,
только если до TCP-серверов не достучаться.
"""

import json
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from modules.errors import ChimeraError
from modules.proxy import parser

MAX_BYTES = 2 << 20
FETCH_TIMEOUT = 20
PING_TIMEOUT = 3.0
MAX_SERVERS = 200
UDP_TYPES = ("hysteria", "hysteria2", "tuic", "wireguard")
# Провайдеры отдают формат по User-Agent: с этим приходит base64-список ссылок
USER_AGENT = "v2rayN/7.0 (Chimera)"


def is_subscription_url(raw) -> bool:
    if not isinstance(raw, str) or "\n" in raw.strip():
        return False
    u = urlsplit(raw.strip())
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and bool(host) and host not in ("t.me", "telegram.me") and bool(
        u.path.strip("/") or u.query)


def fetch(url: str, opener=urllib.request.urlopen) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(req, timeout=FETCH_TIMEOUT) as resp:
            body = resp.read(MAX_BYTES + 1)
    except OSError as e:
        raise ChimeraError("err.proxy.subscription.fetch", error=str(e) or type(e).__name__) from None
    if len(body) > MAX_BYTES:
        raise ChimeraError("err.proxy.subscription.too_big")
    return body.decode("utf-8", "replace")


def _decode(text: str) -> str:
    text = text.strip()
    if "://" in text or text.startswith(("{", "[")):
        return text
    try:
        return parser._b64("".join(text.split())).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return text


def links(text: str) -> list[str]:
    """Серверы из ответа подписки — ссылками, которые понимает parser.parse_link."""
    text = _decode(text)
    candidates = []
    if text.startswith(("{", "[")):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        outbounds = data.get("outbounds", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        candidates = [json.dumps(ob, ensure_ascii=False) for ob in outbounds
                      if isinstance(ob, dict) and ob.get("type") in parser.JSON_TYPES]
    else:
        candidates = [line.strip() for line in text.splitlines() if "://" in line]
    found = []
    for item in candidates:
        if item in found:
            continue
        try:
            parser.parse_link(item)
        except (ValueError, ChimeraError):
            continue
        found.append(item)
        if len(found) >= MAX_SERVERS:
            break
    return found


def summary(link: str) -> dict:
    p = parser.parse_link(link)
    return {"label": p["label"], "server": p["server"], "protocol": p["protocol"]}


def _endpoint(link: str):
    ob = parser.parse_link(link)["outbound"]
    if ob.get("server") and ob.get("server_port"):
        return ob["server"], int(ob["server_port"]), ob["type"]
    peer = (ob.get("peers") or [{}])[0]
    return peer.get("address"), int(peer.get("port") or 0), ob["type"]


def ping(link: str, timeout=PING_TIMEOUT, connect=socket.create_connection, now=time.perf_counter):
    """Задержка TCP-подключения к серверу, мс; None — не ответил или протокол без TCP."""
    try:
        host, port, kind = _endpoint(link)
    except (ValueError, ChimeraError, TypeError):
        return None
    if kind in UDP_TYPES or not host or not port:
        return None
    started = now()
    try:
        connect((host, port), timeout=timeout).close()
    except OSError:
        return None
    return round((now() - started) * 1000)


def ping_all(servers: list[str], ping_fn=ping) -> list:
    if not servers:
        return []
    with ThreadPoolExecutor(max_workers=min(32, len(servers))) as pool:
        return list(pool.map(ping_fn, servers))


def choose(servers: list[str], pings: list) -> int:
    """Самый быстрый TCP-сервер; не ответил ни один — первый QUIC; иначе первый в списке."""
    measured = [(ms, i) for i, ms in enumerate(pings) if ms is not None]
    if measured:
        return min(measured)[1]
    for i, link in enumerate(servers):
        try:
            if _endpoint(link)[2] in UDP_TYPES:
                return i
        except (ValueError, ChimeraError, TypeError):
            continue
    return 0
