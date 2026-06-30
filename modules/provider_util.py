"""Валидация и id для пользовательских DNS-провайдеров (DNS Jumper и Hosts)."""

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
            raise ValueError(f"«{it}» — не похоже на IP-адрес")
        out.append(it)
    return out


def validate_doh(url: str) -> str:
    """Пустая строка допустима (DoH необязателен). Иначе — http(s)-URL."""
    url = (url or "").strip()
    if not url:
        return ""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("DoH-адрес должен быть вида https://host/dns-query")
    return url


def validate_host(host: str) -> str:
    """Пустая строка допустима (DoT необязателен). Иначе — hostname без схемы/порта."""
    host = (host or "").strip().lower()
    if not host:
        return ""
    if "." in host and re.fullmatch(r"[a-z0-9.-]+", host):
        return host
    raise ValueError("DoT-адрес — это хост, напр. dns.example.com")


def unique_id(name: str, existing) -> str:
    """Слаг из имени, уникальный среди existing."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "dns"
    existing = set(existing)
    cid, n = base, 2
    while cid in existing:
        cid, n = f"{base}-{n}", n + 1
    return cid
