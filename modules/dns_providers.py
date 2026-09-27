"""Единый список DNS-провайдеров для всех вкладок.

Встроенные — в dns_providers.json (в репозитории), пользовательские — в
dns_providers.user.json рядом (gitignore). Поле `unblock`: умеет ли провайдер
обходить блокировки, подменяя IP на свой прокси (true у xbox/comss/malw),
или это обычный честный резолвер (false — Cloudflare, Google...).

DNS-вкладка использует всех, у кого есть IP-серверы (их ставят системным DNS).
Hosts-вкладка — только тех, у кого unblock=true (остальные там бесполезны).
"""

import json
from pathlib import Path

from . import paths
from .provider_util import parse_servers, unique_id, validate_doh, validate_host

BUILTIN_PATH = Path(__file__).parent / "dns_providers.json"
USER_PATH = paths.data_path("dns_providers.user.json")
paths.migrate(Path(__file__).parent / "dns_providers.user.json", USER_PATH)  # разовый перенос со старого места


def _load_user() -> list[dict]:
    if USER_PATH.exists():
        try:
            return json.loads(USER_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _save_user(items: list[dict]) -> None:
    USER_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all() -> list[dict]:
    builtin = json.loads(BUILTIN_PATH.read_text(encoding="utf-8"))
    for p in builtin:
        p["builtin"] = True
    user = _load_user()
    for p in user:
        p["builtin"] = False
    return builtin + user


def get(provider_id: str) -> dict:
    for p in load_all():
        if p["id"] == provider_id:
            return p
    raise KeyError(f"DNS-провайдер {provider_id} не найден")


def add(name: str, servers="", ipv6="", doh: str = "", dot: str = "",
        unblock: bool = False, filtering: bool = False) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Введи название провайдера")
    doh = validate_doh(doh)
    dot = validate_host(dot)
    ips = parse_servers(servers)
    ip6 = parse_servers(ipv6)
    if not (ips or ip6 or doh or dot):
        raise ValueError("Укажи IP-сервер (IPv4/IPv6) или DoH/DoT-адрес")
    existing = {p["id"] for p in load_all()}
    provider = {"id": unique_id(name, existing), "name": name,
                "servers": ips, "ipv6": ip6, "doh": doh, "dot": dot,
                "unblock": bool(unblock), "filter": bool(filtering)}
    _save_user(_load_user() + [provider])
    return provider


def delete(provider_id: str) -> None:
    user = _load_user()
    if not any(p["id"] == provider_id for p in user):
        raise ValueError("Встроенного провайдера удалить нельзя")
    _save_user([p for p in user if p["id"] != provider_id])
