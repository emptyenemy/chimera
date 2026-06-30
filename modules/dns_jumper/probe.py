"""Проба возможностей DNS-сервера по факту: DNSSEC-валидация, обход блокировок,
фильтрация рекламы. Нужна, чтобы теги определялись для ЛЮБОГО провайдера (включая
добавленные пользователем), а не брались из заранее проставленной метки.

Методы проверки:
  • DNSSEC — запрос к домену со специально битой подписью (dnssec-failed.org):
             валидирующий резолвер отвечает SERVFAIL, невалидирующий молча отдаёт битый ответ;
  • обход  — резолвим тест-домен (напр. chatgpt.com) через этот DNS и проверяем
             достижимость полученного IP (TCP+TLS с SNI, как blockcheck). Работает —
             значит этот DNS даёт пригодный ответ для заблокированного домена;
  • реклама — резолвим популярный рекламный домен (напр. doubleclick.net): NXDOMAIN,
             0.0.0.0/127.0.0.1 или пустой ответ = провайдер его режет.

ВНИМАНИЕ: «обход» меряется фактической достижимостью с этой машины — если активен
winws2/прокси, результат отражает и их (как в blockcheck). Чистый тест DNS — без них.
"""

import socket
import ssl
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..hosts.resolver import _build_query, _parse_a_records

DNSSEC_BAD = "dnssec-failed.org"          # домен с заведомо битой DNSSEC-подписью
CONTROL_DOMAIN = "example.com"            # «живой» контроль: сервер вообще отвечает?
BLOCKED_IPS = {"0.0.0.0", "127.0.0.1", "::", "::1"}
# статусы «TLS прошёл, но сервис не отдаёт контент» — гео/правовой блок (как 403 у chatgpt):
# обходной DNS вернёт IP прокси в разрешённом регионе и получит 2xx/3xx, обычный — 403.
BLOCK_STATUSES = {403, 451}

RCODE_NOERROR, RCODE_SERVFAIL, RCODE_NXDOMAIN = 0, 2, 3

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
try:
    _ssl_ctx.set_alpn_protocols(["http/1.1"])
except NotImplementedError:
    pass


def _http_status(ip: str, host: str, timeout: float) -> int | None:
    """Код HTTP-ответа сервиса при заходе на IP с нужным SNI (как браузер).
    None — не достучались (TLS оборван/таймаут/не HTTP)."""
    try:
        with socket.create_connection((ip, 443), timeout=timeout) as sock:
            with _ssl_ctx.wrap_socket(sock, server_hostname=host) as tls:
                tls.sendall((f"HEAD / HTTP/1.1\r\nHost: {host}\r\n"
                             "User-Agent: Mozilla/5.0\r\nAccept: */*\r\n"
                             "Connection: close\r\n\r\n").encode("ascii", "ignore"))
                head = tls.recv(64)
    except (OSError, ssl.SSLError):
        return None
    if head[:5] != b"HTTP/":
        return None
    parts = head.split(b" ", 2)
    return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None


def _family(server: str) -> int:
    return socket.AF_INET6 if ":" in server else socket.AF_INET


def _raw_udp(server: str, name: str, timeout: float) -> bytes:
    with socket.socket(_family(server), socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(_build_query(name), (server, 53))
        data, _ = s.recvfrom(4096)
        return data


def _raw_tcp(server: str, name: str, timeout: float) -> bytes:
    pkt = _build_query(name)
    with socket.socket(_family(server), socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect((server, 53))
        s.sendall(struct.pack(">H", len(pkt)) + pkt)
        prefix = s.recv(2)
        if len(prefix) < 2:
            return b""
        need = struct.unpack(">H", prefix)[0]
        buf = b""
        while len(buf) < need:
            chunk = s.recv(need - len(buf))
            if not chunk:
                break
            buf += chunk
        return buf


def _query(server: str, name: str, timeout: float = 4.0):
    """A-запрос к серверу: UDP и TCP параллельно, берём первый ответ. Так проба
    остаётся быстрой и там, где UDP-53 зарезан (sing-box TUN, файрвол).
    Возвращает (rcode, [ips]) или (None, []) если сервер не ответил."""
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        futures = [pool.submit(_raw_udp, server, name, timeout),
                   pool.submit(_raw_tcp, server, name, timeout)]
        for fut in as_completed(futures):
            try:
                data = fut.result()
            except OSError:
                data = b""
            if data and len(data) >= 4:
                return data[3] & 0x0F, _parse_a_records(data)
        return None, []
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def probe(servers: list[str], bypass_domains: list[str], ad_domain: str,
          timeout: float = 4.0) -> dict:
    """Гоняет пробу по первому ответившему серверу провайдера.
    Возвращает {reachable, dnssec, filter, unblock, unblock_detail}; значение None —
    проверку не делали (нет тест-домена) или сервер не ответил."""
    server = next((s for s in servers if _query(server=s, name=CONTROL_DOMAIN,
                                                timeout=timeout)[0] is not None), None)
    if server is None:
        return {"reachable": False, "dnssec": None, "filter": None,
                "unblock": None, "unblock_detail": {}}

    out = {"reachable": True}

    # DNSSEC: битая подпись -> валидирующий резолвер вернёт SERVFAIL
    rc, _ = _query(server, DNSSEC_BAD, timeout)
    out["dnssec"] = rc == RCODE_SERVFAIL

    # реклама: режет ли рекламный домен (NXDOMAIN / sentinel-IP / пусто)
    if ad_domain:
        rc, ips = _query(server, ad_domain, timeout)
        out["filter"] = (rc == RCODE_NXDOMAIN or not ips
                         or all(ip in BLOCKED_IPS for ip in ips))
    else:
        out["filter"] = None

    # обход: резолвим домен через этот DNS и смотрим HTTP-статус сервиса по
    # полученному IP. Успех = реальный ответ (2xx/3xx); 403/451 = блок (гео/право),
    # нет ответа = блок по сети (RST/таймаут). Так маркер отличает обходной DNS.
    detail = {}
    for d in bypass_domains:
        _, ips = _query(server, d, timeout)
        ok = False
        for ip in ips[:2]:
            st = _http_status(ip, d, timeout)
            if st is not None and st not in BLOCK_STATUSES:
                ok = True
                break
        detail[d] = ok
    out["unblock"] = all(detail.values()) if detail else None
    out["unblock_detail"] = detail
    return out
