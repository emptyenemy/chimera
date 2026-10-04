"""Провайдер пользователя и карта того, что у кого сработало.

Провайдер — номер сети (AS) по данным RIPEstat, открытого сервиса реестра RIPE NCC: своего
сервера у Chimera нет, адрес спрашивает сам RIPEstat. Запрос уходит, только когда он нужен:
по кнопке «Поделиться результатом» или когда в карте есть провайдеры, и раз на сеть —
ответ запоминается вместе с памятью сети.

Карта (strategies/provider-map.json) собирается из отчётов пользователей в issues
(tools/provider_map.py) и приходит с обновлением данных. Варианты, которые сработали у того
же провайдера, автонастройка пробует первыми — сразу после запомненных для этой сети.
Карта меняет только порядок перебора: остальные варианты пробуются как обычно.
"""

import json
import urllib.request

from modules import paths

MAP_PATH = paths.APP_DIR / "strategies" / "provider-map.json"
RIPESTAT = "https://stat.ripe.net/data/{}/data.json?sourceapp=chimera{}"
TIMEOUT = 4
STEPS = ("strategy", "hosts", "dns")   # прокси у каждого свой — подсказывать нечего


def _fetch(endpoint: str, resource: str = "") -> dict:
    url = RIPESTAT.format(endpoint, f"&resource={resource}" if resource else "")
    request = urllib.request.Request(url, headers={"User-Agent": "Chimera"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
        return json.loads(reply.read(1 << 20))


def lookup(fetch=_fetch) -> dict | None:
    """{"asn": 25513, "name": "владелец сети"} или None, если RIPEstat не ответил."""
    try:
        ip = fetch("whats-my-ip")["data"]["ip"]
        asn = int(fetch("network-info", ip)["data"]["asns"][0])
        holder = fetch("as-overview", f"AS{asn}")["data"].get("holder") or ""
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None
    if asn <= 0:
        return None
    return {"asn": asn, "name": str(holder)[:80]}


def load_map(path=MAP_PATH) -> dict:
    """{"<asn>": {"name": ..., "services": {сервис: [{"kind", "id", "n"}, ...]}}}; битый файл — пусто."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    providers = data.get("providers") if isinstance(data, dict) else None
    return providers if isinstance(providers, dict) else {}


def hints(providers: dict, provider: dict | None) -> dict:
    """{сервис: [{"kind", "id"}, ...]} для провайдера — по убыванию числа отчётов."""
    entry = providers.get(str(provider["asn"])) if provider else None
    services = entry.get("services") if isinstance(entry, dict) else None
    if not isinstance(services, dict):
        return {}
    result = {}
    for name, fixes in services.items():
        if not isinstance(fixes, list):
            continue
        good = [f for f in fixes if isinstance(f, dict) and f.get("kind") in STEPS and isinstance(f.get("id"), str)]
        good.sort(key=lambda f: -f["n"] if isinstance(f.get("n"), int) else 0)
        if good:
            result[str(name)] = [{"kind": f["kind"], "id": f["id"]} for f in good]
    return result
