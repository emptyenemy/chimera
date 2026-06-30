"""Локальная проверка достижимости доменов («blockcheck»).

В отличие от cheburcheck (сверка с реестром РКН — заблокирован ли домен официально),
здесь меряем ПРАКТИЧЕСКУЮ достижимость с этой машины и с текущими настройками —
ровно как если бы пользователь сам открыл сайт в браузере. Ничего не обходим:
идём штатным путём ОС (системный резолвер → TCP → TLS с настоящим SNI) и смотрим,
прошёл ли хендшейк или прилетел RST/таймаут (типовая картина SNI-блокировки DPI).

Как браузер (Happy Eyeballs, RFC 8305): домен часто резолвится в несколько адресов
(IPv4 + IPv6). Браузер пробует их и берёт тот, что реально заработал. Мы делаем так же —
перебираем адреса (IPv4 вперёд: в сетях с обходом он надёжнее и именно его берёт
фолбэк браузера), «ok» если хоть один прошёл TLS, «blocked» только если упали все.
Иначе чекер цеплялся бы за первый адрес (нередко мёртвый IPv6) и врал бы про блок.

windivert2 здесь не нужен: драйвер требуется winws2, чтобы ПРИМЕНЯТЬ обход, а мы лишь
НАБЛЮДАЕМ результат. Это не ICMP-ping (он не отражает SNI-блок и часто фильтруется) —
меряем TCP+TLS на 443 с правильным server_name, что и показывает блок/обход.
"""

import socket
import ssl
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

CONNECT_TIMEOUT = 4.0  # на каждый адрес отдельно
OVERALL_TIMEOUT = 5.0  # потолок на весь домен (адреса идут параллельно)
MAX_ADDRS = 6          # не плодить потоки на домены с кучей A/AAAA
PORT = 443

# серт не валидируем: при DNS-подмене за доменом часто «чужой» серт — это норма,
# нам важен не серт, а дошёл ли реальный HTTP-ответ.
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
try:
    # только http/1.1: с h2 сервер ответит бинарным фреймом, а нам нужен текст "HTTP/..".
    _ssl_ctx.set_alpn_protocols(["http/1.1"])
except NotImplementedError:
    pass


def _http_request(target: str) -> bytes:
    return (
        f"HEAD / HTTP/1.1\r\nHost: {target}\r\n"
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
        "Accept: */*\r\nConnection: close\r\n\r\n"
    ).encode("ascii", "ignore")


def check(target: str) -> dict:
    """Проверка одного домена с текущими настройками. Статусы:
      ok      — TLS-handshake прошёл хотя бы по одному адресу, домен достижим;
      blocked — все адреса оборвались (RST/timeout) — похоже на DPI/IP-блок;
      dns     — домен не резолвится (возможна DNS-блокировка);
      error   — прочая ошибка.
    Возвращает {target, status, ip, ms, reason}. Для ok reason = семейство (IPv4/IPv6).
    """
    target = (target or "").strip()
    if not target:
        raise ValueError("Пустой домен")
    started = time.monotonic()

    # 1) DNS через системный резолвер — уважает текущие DNS/hosts (как браузер).
    try:
        addrs = _resolve(target)
    except socket.gaierror:
        return _result(target, "dns", None, started, "не резолвится")
    if not addrs:
        return _result(target, "dns", None, started, "нет адресов")

    # 2) как браузер (Happy Eyeballs): гоним адреса параллельно, первый прошедший
    #    TLS = достижим. Так общий домен укладывается в OVERALL_TIMEOUT независимо
    #    от числа адресов, а мёртвый IPv6 не задерживает рабочий IPv4.
    pool = ThreadPoolExecutor(max_workers=len(addrs))
    fut_addr = {pool.submit(_try_one, ip, target): (family, ip) for family, ip in addrs}
    pending = set(fut_addr)
    last_ip, last_reason = addrs[-1][1], "таймаут"
    ok_ip, ok_family = None, None
    deadline = time.monotonic() + OVERALL_TIMEOUT
    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                break  # дедлайн
            stop = False
            for fut in done:
                family, ip = fut_addr[fut]
                ok, reason = fut.result()
                if ok:
                    ok_ip, ok_family, stop = ip, family, True
                    break
                last_ip, last_reason = ip, reason
            if stop:
                break
    finally:
        pool.shutdown(wait=False)  # рабочий найден — на отстающих не ждём

    if ok_ip:
        fam = "IPv6" if ok_family == socket.AF_INET6 else "IPv4"
        return _result(target, "ok", ok_ip, started, fam)
    return _result(target, "blocked", last_ip, started, last_reason)


def _resolve(target: str) -> list[tuple[int, str]]:
    """Уникальные адреса домена, IPv4 раньше IPv6. [(family, ip), ...]."""
    infos = socket.getaddrinfo(target, PORT, type=socket.SOCK_STREAM)
    v4 = [i for i in infos if i[0] == socket.AF_INET]
    v6 = [i for i in infos if i[0] == socket.AF_INET6]
    seen, ordered = set(), []
    for fam, *_rest, sockaddr in (*v4, *v6):
        ip = sockaddr[0]
        if ip not in seen:
            seen.add(ip)
            ordered.append((fam, ip))
    return ordered[:MAX_ADDRS]


def _try_one(ip: str, target: str) -> tuple[bool, str | None]:
    """Полный заход на один адрес как браузер: TCP → TLS(SNI) → HTTP-запрос → ответ.

    «ok» только если пришёл реальный ответ `HTTP/..`. Один лишь TLS-хендшейк — слабый
    сигнал: край CDN (Cloudflare и пр.) жмёт руку любому SNI, а DPI рвёт уже на запросе.
    Поэтому ждём именно HTTP-ответ — это и значит «сайт реально отвечает».
    """
    try:
        with socket.create_connection((ip, PORT), timeout=CONNECT_TIMEOUT) as sock:
            try:
                tls = _ssl_ctx.wrap_socket(sock, server_hostname=target)
            except (ssl.SSLError, OSError):
                return False, "TLS оборван (DPI?)"
            with tls:
                try:
                    tls.sendall(_http_request(target))
                    head = tls.recv(64)
                except (socket.timeout, TimeoutError):
                    return False, "нет ответа на запрос (DPI?)"
                except OSError:
                    return False, "оборвано на запросе (DPI?)"
                if head[:5] == b"HTTP/":
                    return True, None
                return False, "не HTTP-ответ"
    except (socket.timeout, TimeoutError):
        return False, "таймаут"
    except ConnectionResetError:
        return False, "RST на TCP"
    except OSError as e:
        return False, _short(e)


def _result(target, status, ip, started, reason) -> dict:
    return {
        "target": target,
        "status": status,
        "ip": ip,
        "ms": int((time.monotonic() - started) * 1000),
        "reason": reason,
    }


def _short(e: OSError) -> str:
    msg = (getattr(e, "strerror", None) or str(e) or "ошибка сети").strip()
    return msg[:60]
