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

Выборочный прокси (modules/proxy) в режиме PAC — это особый случай: он не виден
обычным сокетам (PAC читает только браузер), поэтому домен, реально уходящий через
прокси у пользователя, голым сокетом отсюда выглядел бы заблокированным — наврали бы.
Если вызывающий код передаёт socks_addr (когда домен входит в список прокси и тот
запущен), проверка идёт через локальный SOCKS5 — ровно тем же путём, что и браузер.
В режиме TUN такого зазора нет: там трафik заворачивается на уровне ОС, обычный
сокет и так пойдёт через прокси — отдельной обработки не требуется.
"""

import re
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


def check(target: str, socks_addr: tuple[str, int] | None = None) -> dict:
    """Проверка одного домена с текущими настройками. Статусы:
      ok        — реальный 2xx/3xx HTTP-ответ хотя бы по одному адресу, домен достижим;
      challenge — это Cloudflare-челлендж (JS/Turnstile, заголовок Cf-Mitigated:
                  challenge) — браузер обычно проходит его сам за секунду-две,
                  это НЕ отказ и НЕ DPI, просто мы его не решаем — статус «не уверены»;
      denied    — соединение и TLS прошли, сервер ответил, HTTP-код 4xx/5xx и это НЕ
                  челлендж — настоящий отказ САЙТА (например, гео-бан по IP), а не
                  DPI; обход тут не поможет, нужен VPN/прокси с не-российским адресом;
      blocked   — все адреса оборвались (RST/timeout) до HTTP-ответа — похоже на DPI/IP-блок;
      dns       — домен не резолвится (возможна DNS-блокировка);
      error     — прочая ошибка.
    Возвращает {target, status, ip, ms, reason}. Для ok reason = семейство (IPv4/IPv6).

    socks_addr — (host, port) локального SOCKS5 (наш sing-box), если вызывающий код
    знает, что в PAC-режиме этот домен реально маршрутизируется через прокси. Тогда
    идём ровно тем путём (см. докстринг модуля), а не напрямую.
    """
    target = (target or "").strip()
    if not target:
        raise ValueError("Пустой домен")
    started = time.monotonic()

    if socks_addr:
        status, detail = _try_via_proxy(socks_addr, target)
        if status == "ok":
            return _result(target, "ok", None, started, "через прокси", via="proxy")
        if status in ("challenge", "denied"):
            return _result(target, status, None, started, _describe(status, detail), via="proxy")
        return _result(target, "blocked", None, started, detail, via="proxy")

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
    chal_ip, chal_code = None, None
    denied_ip, denied_code = None, None
    deadline = time.monotonic() + OVERALL_TIMEOUT
    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                break  # дедлайн
            # сначала разбираем всю пачку готовых — приоритет ok > challenge > denied,
            # даже если несколько прилетели в одном батче (разные адреса того же домена)
            for fut in done:
                family, ip = fut_addr[fut]
                status, detail = fut.result()
                if status == "ok":
                    ok_ip, ok_family = ip, family
                elif status == "challenge" and chal_ip is None:
                    chal_ip, chal_code = ip, detail
                elif status == "denied" and denied_ip is None:
                    denied_ip, denied_code = ip, detail
                else:
                    last_ip, last_reason = ip, detail
            if ok_ip or chal_ip or denied_ip:
                break
    finally:
        pool.shutdown(wait=False)  # рабочий найден — на отстающих не ждём

    if ok_ip:
        fam = "IPv6" if ok_family == socket.AF_INET6 else "IPv4"
        return _result(target, "ok", ok_ip, started, fam)
    if chal_ip:
        return _result(target, "challenge", chal_ip, started, _describe("challenge", chal_code))
    if denied_ip:
        return _result(target, "denied", denied_ip, started, _describe("denied", denied_code))
    return _result(target, "blocked", last_ip, started, last_reason)


def _describe(status: str, code: int) -> str:
    return f"HTTP {code} (Cloudflare)" if status == "challenge" else f"HTTP {code} (отказ сайта)"


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


_STATUS_RE = re.compile(rb"^HTTP/\d\.\d (\d{3})")
# Managed/JS-challenge Cloudflare помечает этим заголовком на самом ответе — отличает
# временный «докажи, что не бот» (браузер проходит сам за 1-2 сек, кука cf_clearance)
# от настоящего отказа (geo-ban и т.п., такого заголовка не несёт).
_CF_CHALLENGE_RE = re.compile(rb"(?im)^cf-mitigated:\s*challenge\s*$")
HEADERS_LIMIT = 8192  # с запасом: у CF сайтов под защитой бывает за 1-1.5КБ одних заголовков


def _read_headers(tls) -> bytes:
    """Читает до конца заголовков (\\r\\n\\r\\n) или до HEADERS_LIMIT/конца ответа."""
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < HEADERS_LIMIT:
        chunk = tls.recv(2048)
        if not chunk:
            break
        buf += chunk
    return buf


def _classify(sock: socket.socket, target: str) -> tuple[str, str | int | None]:
    """TLS(SNI) → HTTP-запрос → классификация ответа. sock уже TCP-соединён с целью
    (напрямую или через локальный SOCKS5 — для классификации разницы нет).

    Один лишь TLS-хендшейк — слабый сигнал: край CDN (Cloudflare и пр.) жмёт руку
    любому SNI, а DPI рвёт уже на запросе. Поэтому ждём именно HTTP-ответ — это и
    значит «сайт реально отвечает». Но и сам HTTP-ответ ещё не значит «доступен»:
    4xx/5xx — это полноценный ответ настоящего сервера, а не DPI, но дальше есть
    два разных случая: Cloudflare-челлендж (browser проходит сам — "challenge")
    и настоящий отказ сайта, например гео-бан ("denied").

    Возвращает (status, detail): status="ok"/"challenge"/"denied"/"fail";
    detail — код статуса для challenge/denied, причина для fail, None для ok.
    """
    try:
        tls = _ssl_ctx.wrap_socket(sock, server_hostname=target)
    except (ssl.SSLError, OSError):
        return "fail", "TLS оборван (DPI?)"
    with tls:
        try:
            tls.sendall(_http_request(target))
            head = _read_headers(tls)
        except TimeoutError:
            return "fail", "нет ответа на запрос (DPI?)"
        except OSError:
            return "fail", "оборвано на запросе (DPI?)"
        m = _STATUS_RE.match(head)
        if not m:
            return "fail", "не HTTP-ответ"
        code = int(m.group(1))
        if 400 <= code < 600:
            return ("challenge" if _CF_CHALLENGE_RE.search(head) else "denied"), code
        return "ok", None


def _try_one(ip: str, target: str) -> tuple[str, str | int | None]:
    """Полный заход на один адрес как браузер: TCP → _classify."""
    try:
        with socket.create_connection((ip, PORT), timeout=CONNECT_TIMEOUT) as sock:
            return _classify(sock, target)
    except TimeoutError:
        return "fail", "таймаут"
    except ConnectionResetError:
        return "fail", "RST на TCP"
    except OSError as e:
        return "fail", _short(e)


def _try_via_proxy(proxy_addr: tuple[str, int], target: str) -> tuple[str, str | int | None]:
    """То же самое, но TCP-соединение идёт не напрямую, а CONNECT'ом через локальный
    SOCKS5 (наш sing-box) — домен резолвит и тянет уже прокси-сервер на том конце."""
    try:
        with _socks5_connect(proxy_addr, target, PORT, CONNECT_TIMEOUT) as sock:
            return _classify(sock, target)
    except TimeoutError:
        return "fail", "таймаут до локального прокси"
    except OSError as e:
        return "fail", f"локальный прокси: {_short(e)}"


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("SOCKS5: соединение оборвано")
        buf += chunk
    return buf


def _socks5_connect(proxy_addr: tuple[str, int], target: str, port: int, timeout: float) -> socket.socket:
    """Минимальный SOCKS5 CONNECT без авторизации — ровно то, что отдаёт mixed-inbound
    sing-box на 127.0.0.1 в PAC-режиме (modules/proxy/manager.py). Адрес-домен (не IP)
    передаём как есть — пусть резолвит и маршрутизирует сам прокси, как для браузера.
    """
    sock = socket.create_connection(proxy_addr, timeout=timeout)
    sock.settimeout(timeout)
    try:
        sock.sendall(b"\x05\x01\x00")  # ver=5, 1 метод авторизации: no-auth
        if _recv_exact(sock, 2) != b"\x05\x00":
            raise OSError("SOCKS5: прокси отказал в no-auth")
        host = target.encode("ascii")
        req = b"\x05\x01\x00\x03" + bytes([len(host)]) + host + port.to_bytes(2, "big")
        sock.sendall(req)
        head = _recv_exact(sock, 4)
        if head[1] != 0x00:
            raise OSError(f"SOCKS5: CONNECT отказан (код {head[1]})")
        atyp = head[3]
        if atyp == 0x01:
            _recv_exact(sock, 4 + 2)
        elif atyp == 0x03:
            n = _recv_exact(sock, 1)[0]
            _recv_exact(sock, n + 2)
        elif atyp == 0x04:
            _recv_exact(sock, 16 + 2)
        else:
            raise OSError("SOCKS5: неизвестный тип адреса в ответе")
    except BaseException:
        sock.close()
        raise
    return sock


def _result(target, status, ip, started, reason, via=None) -> dict:
    r = {
        "target": target,
        "status": status,
        "ip": ip,
        "ms": int((time.monotonic() - started) * 1000),
        "reason": reason,
    }
    if via:
        r["via"] = via
    return r


def _short(e: OSError) -> str:
    msg = (getattr(e, "strerror", None) or str(e) or "ошибка сети").strip()
    return msg[:60]
