"""Валидация и id для пользовательских DNS-провайдеров (DNS Jumper и Hosts)."""

from modules.errors import ChimeraValueError

import ipaddress
import re
from urllib.parse import urlparse


def parse_servers(raw) -> list[str]:
    """raw — строка (IP через пробел/запятую) или список. Возвращает валидные IP."""
    items = re.split(r"[\s,;]+", raw.strip()) if isinstance(raw, str) else list(raw or [])
    out = []
    for it in items:
        it = (it or "").strip()
        if not it:
            continue
        try:
            ipaddress.ip_address(it)
        except ValueError:
            raise ChimeraValueError('err.provider_util.does_not_look_like_an_ip_address', p0=it) from None
        out.append(it)
    return out


def validate_doh(url: str) -> str:
    """Пустая строка допустима (DoH необязателен). Иначе — http(s)-URL."""
    url = (url or "").strip()
    if not url:
        return ""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ChimeraValueError('err.provider_util.a_doh_address_must_have_the_form_https_host_dns')
    return url


def validate_host(host: str) -> str:
    """Пустая строка допустима (DoT необязателен). Иначе — hostname без схемы/порта."""
    host = (host or "").strip().lower()
    if not host:
        return ""
    if "." in host and re.fullmatch(r"[a-z0-9.-]+", host):
        return host
    raise ChimeraValueError('err.provider_util.a_dot_address_must_be_a_hostname_such_as_dns_exa')


def unique_id(name: str, existing) -> str:
    """Слаг из имени, уникальный среди existing."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "dns"
    existing = set(existing)
    cid, n = base, 2
    while cid in existing:
        cid, n = f"{base}-{n}", n + 1
    return cid
