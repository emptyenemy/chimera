"""Проверка блокировок через cheburcheck.ru — заблокирован ли домен в реестрах РКН.

Лёгкая обёртка над публичным API (https://cheburcheck.ru/api/v1):
  GET /status          → версия сервиса, дата обновления реестра, размер базы
  GET /check?target=X  → {blocked, rkn_domain, ips, blocked_subnets, cdn_providers,
                          geo, whitelist, reverse_lookup, target_type, ...}

Своего кода проверки не держим — это онлайн-сервис LowderPlay/cheburcheck.
Версия показывается в UI и берётся прямо из /status (не из нашего кода).
"""

import json
import time
import urllib.parse
import urllib.request

API = "https://cheburcheck.ru/api/v1"
UA = {"User-Agent": "chimera"}
TIMEOUT = 15

_status_cache: dict | None = None
_status_at = 0.0
_STATUS_TTL = 300  # статус реестра меняется редко — кэшируем на 5 минут


def _get(path: str) -> dict:
    req = urllib.request.Request(API + path, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def status(force: bool = False) -> dict:
    """Версия сервиса, дата обновления реестра РКН и размер базы."""
    global _status_cache, _status_at
    if not force and _status_cache and time.monotonic() - _status_at < _STATUS_TTL:
        return _status_cache
    data = _get("/status")
    _status_cache = {
        "version": data.get("version"),
        "domain_count": data.get("domain_count"),
        "v4_count": data.get("v4_count"),
        "last_update": data.get("last_update"),
    }
    _status_at = time.monotonic()
    return _status_cache


def check(target: str) -> dict:
    """Проверка одного домена/IP. Возвращает компактный результат для UI.

    При rate-limit (429) повторяем с нарастающей паузой — публичный API
    притормаживает пачки, но обычно пускает со второй-третьей попытки.
    """
    target = (target or "").strip()
    if not target:
        raise ValueError("Пустой домен")
    d = None
    for attempt in range(3):
        try:
            d = _get("/check?target=" + urllib.parse.quote(target))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            if e.code == 429:
                return {"target": target, "status": "rate", "blocked": None}
            raise
    return _shape(target, d)


def _shape(target: str, d: dict) -> dict:
    """Полный ответ /check → компактная структура для UI (берём всё полезное).

    Сервис отдаёт куда больше, чем просто blocked: гео IP (страна/организация/ASN),
    реально заблокированные подсети, ранг популярности из whitelist и обратные
    DNS-записи. Тащим всё — UI решает, что показать.
    """
    geo = d.get("geo") or {}
    wl = d.get("whitelist") or {}
    country = (geo.get("location") or geo.get("country_code") or "").strip()
    if country in ("", "-"):  # сервис отдаёт «-», когда страна неизвестна
        country = None
    has_geo = any(geo.get(k) for k in ("location", "country_code", "organisation", "asn"))
    return {
        "target": target,
        "type": d.get("target_type"),                  # «Домен» / «IP»
        "status": "blocked" if d.get("blocked") else "free",
        "blocked": bool(d.get("blocked")),
        "rkn_domain": d.get("rkn_domain"),             # домен в реестре РКН (если по домену)
        "ips": d.get("ips") or [],                     # резолв (IPv4 + IPv6)
        "subnets": d.get("blocked_subnets") or [],     # реально заблокированные подсети
        "cdn": list((d.get("cdn_providers") or {}).keys()),
        "geo": {                                       # где живёт IP
            "country": country,
            "org": geo.get("organisation"),
            "asn": geo.get("asn"),
        } if has_geo else None,
        "rank": wl.get("rank"),                        # ранг популярности (whitelist)
        "last_ok": wl.get("last_ok"),                  # когда последний раз был доступен
        "ptr": d.get("reverse_lookup") or [],          # обратные DNS-записи (PTR)
    }
