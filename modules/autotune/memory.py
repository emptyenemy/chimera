"""Память сетей: какой вариант починил сервис в этой сети — его и пробуем первым.

Ключ сети — адаптер, через который сейчас интернет, и его подсеть /24. Совпадение
ключа у двух разных сетей безвредно: запомненный вариант просто проверяется первым.
"""

import hashlib
import json
import time

from modules import paths
from modules.fileutil import atomic_write_text

PATH = paths.data_path("autotune-memory.json")
MAX_NETWORKS = 20


def network_key(adapters) -> str | None:
    # адаптеры уже отсортированы: подключённые физические первыми, TUN прокси — после них
    for a in adapters:
        if a.get("status") == "Up" and a.get("ipv4"):
            subnet = ".".join(a["ipv4"][0].split(".")[:3])
            return hashlib.sha256(f"{a.get('guid')}|{subnet}".encode()).hexdigest()[:16]
    return None


def _read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(key, path=PATH) -> dict:
    """{сервис: {"kind": шаг, "id": вариант}} для сети; пусто, если сеть новая."""
    if not key:
        return {}
    network = _read(path).get(key)
    services = network.get("services") if isinstance(network, dict) else None
    if not isinstance(services, dict):
        return {}
    return {name: fix for name, fix in services.items()
            if isinstance(fix, dict) and isinstance(fix.get("kind"), str) and isinstance(fix.get("id"), str)}


def provider(key, path=PATH) -> dict | None:
    """Провайдер сети, если его уже узнавали (modules/autotune/provider.py)."""
    network = _read(path).get(key) if key else None
    found = network.get("provider") if isinstance(network, dict) else None
    if isinstance(found, dict) and type(found.get("asn")) is int and isinstance(found.get("name"), str):
        return {"asn": found["asn"], "name": found["name"]}
    return None


def remember(key, fixes, path=PATH, now=time.time) -> None:
    if not key or not fixes:
        return

    def change(network):
        services = network.get("services") if isinstance(network.get("services"), dict) else {}
        services.update({name: {"kind": fix["kind"], "id": fix["id"]} for name, fix in fixes.items()})
        network["services"] = services
    _update(key, change, path, now)


def remember_provider(key, found, path=PATH, now=time.time) -> None:
    if key and found:
        _update(key, lambda network: network.update(provider={"asn": found["asn"], "name": found["name"]}), path, now)


def _update(key, change, path, now) -> None:
    data = _read(path)
    network = dict(data[key]) if isinstance(data.get(key), dict) else {}
    change(network)
    network["at"] = now()
    data[key] = network
    # старые сети вытесняются, файл не растёт бесконечно
    keep = sorted(data, key=lambda k: data[k].get("at", 0) if isinstance(data[k], dict) else 0, reverse=True)
    data = {k: data[k] for k in keep[:MAX_NETWORKS]}
    try:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        pass  # память — подсказка порядка, без неё подбор всё равно работает
