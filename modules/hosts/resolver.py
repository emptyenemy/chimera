"""Мини-резолвер DNS на stdlib: DoH (RFC 8484, wireformat) с фолбэком на UDP.

Нужен, чтобы прогонять домены через «разблокирующие» DNS (xbox-dns, comss,
malw и т.п.): они отдают вместо оригинального IP адрес своего прокси,
а мы фиксируем его в hosts-файле.
"""

import secrets
import socket
import struct
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

TIMEOUT = 6.0


def _build_query(domain: str) -> bytes:
    header = secrets.token_bytes(2) + struct.pack(">HHHHH", 0x0100, 1, 0, 0, 0)
    qname = b"".join(
        bytes([len(label)]) + label.encode("idna") for label in domain.split(".")
    )
    return header + qname + b"\x00" + struct.pack(">HH", 1, 1)  # QTYPE=A, IN


def _skip_name(data: bytes, off: int) -> int:
    while True:
        length = data[off]
        if length == 0:
            return off + 1
        if length & 0xC0 == 0xC0:  # указатель сжатия
            return off + 2
        off += 1 + length


def _parse_a_records(data: bytes) -> list[str]:
    if len(data) < 12:
        return []
    qdcount, ancount = struct.unpack(">HH", data[4:8])
    off = 12
    for _ in range(qdcount):
        off = _skip_name(data, off) + 4
    ips = []
    for _ in range(ancount):
        off = _skip_name(data, off)
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        if rtype == 1 and rdlen == 4:
            ips.append(socket.inet_ntoa(data[off:off + 4]))
        off += rdlen
    return ips


def _via_doh(domain: str, url: str, timeout: float = TIMEOUT) -> list[str]:
    req = urllib.request.Request(
        url,
        data=_build_query(domain),
        headers={
            "Content-Type": "application/dns-message",
            "Accept": "application/dns-message",
            "User-Agent": "chimera",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _parse_a_records(resp.read())


def _family(server: str) -> int:
    return socket.AF_INET6 if ":" in server else socket.AF_INET


def _via_udp(domain: str, server: str, timeout: float = TIMEOUT) -> list[str]:
    with socket.socket(_family(server), socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(_build_query(domain), (server, 53))
        data, _ = sock.recvfrom(4096)
        return _parse_a_records(data)


def _via_tcp(domain: str, server: str, timeout: float = TIMEOUT) -> list[str]:
    """DNS over TCP (порт 53). Фолбэк для пинга, когда UDP-53 режется
    (sing-box TUN, файрвол): TCP-53 показывает реальную доступность сервера."""
    query = _build_query(domain)
    with socket.socket(_family(server), socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect((server, 53))
        sock.sendall(struct.pack(">H", len(query)) + query)
        prefix = sock.recv(2)
        if len(prefix) < 2:
            return []
        need = struct.unpack(">H", prefix)[0]
        buf = b""
        while len(buf) < need:
            chunk = sock.recv(need - len(buf))
            if not chunk:
                break
            buf += chunk
        return _parse_a_records(buf)


def resolve(domain: str, doh: str | None = None, servers: list[str] | None = None,
            timeout: float = TIMEOUT) -> list[str]:
    """Возвращает A-записи домена; пробует DoH, затем UDP-серверы по очереди."""
    if doh:
        try:
            ips = _via_doh(domain, doh, timeout)
            if ips:
                return ips
        except OSError:
            pass
    for server in servers or []:
        try:
            ips = _via_udp(domain, server, timeout)
            if ips:
                return ips
        except OSError:
            continue
    return []


def timed_resolve(domain: str, doh: str | None = None, servers: list[str] | None = None,
                  timeout: float = TIMEOUT) -> tuple[list[str], int]:
    """Быстрый «пинг» DNS: гонка всех UDP-серверов параллельно, берём первый
    ответивший (его ms). Если серверов нет — пробуем DoH.

    Это не последовательный фолбэк: все запросы летят разом в одно окно timeout,
    поэтому флапающий один IP не делает провайдера «мёртвым» и не копит задержки.
    Возвращает (ips, ms).
    """
    servers = servers or []
    started = time.monotonic()

    if servers:
        pool = ThreadPoolExecutor(max_workers=len(servers))
        try:
            futures = [pool.submit(_via_udp, domain, s, timeout) for s in servers]
            for fut in as_completed(futures):
                try:
                    ips = fut.result()
                except OSError:
                    ips = []
                if ips:
                    return ips, int((time.monotonic() - started) * 1000)
            return [], int((time.monotonic() - started) * 1000)
        finally:
            # не ждём отставших (флапающий IP), они сами завершатся по таймауту
            pool.shutdown(wait=False, cancel_futures=True)

    if doh:
        try:
            ips = _via_doh(domain, doh, timeout)
        except OSError:
            ips = []
        return ips, int((time.monotonic() - started) * 1000)

    return [], 0


def ping_dns(server: str, domain: str = "www.google.com", timeout: float = 3.0) -> dict:
    """Меряет доступность DNS-сервера A-запросом. UDP и TCP гонятся параллельно —
    берём первый ответ: где UDP-53 зарезан (sing-box TUN, файрвол), доступность
    покажет TCP-53. Работает и для IPv4, и для IPv6. ms=None — сервер молчит."""
    started = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        futures = [pool.submit(_via_udp, domain, server, timeout),
                   pool.submit(_via_tcp, domain, server, timeout)]
        for fut in as_completed(futures):
            try:
                ips = fut.result()
            except OSError:
                ips = []
            if ips:
                return {"server": server, "ok": True,
                        "ms": int((time.monotonic() - started) * 1000)}
        return {"server": server, "ok": False, "ms": None}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def resolve_domains(
    domains: list[str],
    doh: str | None = None,
    servers: list[str] | None = None,
    max_workers: int = 8,
) -> list[dict]:
    """Резолвит список доменов в записи [{ip, host}]; нерезолвящиеся пропускает."""
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = pool.map(lambda d: (d, resolve(d, doh, servers)), domains)
    return [{"ip": ips[0], "host": d} for d, ips in results if ips]
