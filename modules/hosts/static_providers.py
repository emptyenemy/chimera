"""Встроенные static-провайдеры hosts — готовый список записей, без резолвинга.

В отличие от DNS-провайдера (домены из lists/*.txt резолвятся на лету через его
DoH/UDP), static-провайдер отдаёт фиксированный набор host -> IP из готового
файла. Первый и пока единственный — hosts-блок Flowseal
(upstream/zapret-discord-youtube/.service/hosts: GitHub, Telegram, Discord CDN).

Файл сабмодуля читается заново при КАЖДОМ применении (см. read_entries) — так
обновление сабмодуля (git submodule update --remote) подхватывается само, без
правок кода. Если сабмодуля нет рядом (собранный exe его не тянет) — провайдер
просто помечается недоступным (available=False, reason) и не участвует в
применении, никаких падений.
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraFileNotFoundError, ChimeraKeyError

from .. import paths

FLOWSEAL_HOSTS_PATH = paths.APP_DIR / "upstream" / "zapret-discord-youtube" / ".service" / "hosts"

# path — Path до исходника; наружу (в API/front) не отдаём, только через providers().
_STATIC = [
    {
        "id": "flowseal-hosts",
        "name": "Flowseal (GitHub/Telegram/Discord)",
        "path": FLOWSEAL_HOSTS_PATH,
    },
]


def parse_hosts_text(text: str) -> list[dict]:
    """Разбор текста в формате hosts: `IP host1 host2 ...`.

    `#` и всё после него на строке — комментарий, пустые строки пропускаются.
    Один IP может нести несколько имён (обычный hosts-синтаксис) — каждое
    становится отдельной записью. Один host может повторяться с разными IP
    (так Flowseal раздаёт discord.com сразу на несколько CDN-адресов) — не
    схлопываем, пишем все, как в исходнике.
    """
    entries = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ip, hosts = parts[0], parts[1:]
        for host in hosts:
            entries.append({"ip": ip, "host": host})
    return entries


def providers() -> list[dict]:
    """Публичный список static-провайдеров для UI (JSON-safe, без Path)."""
    out = []
    for p in _STATIC:
        available = p["path"].exists()
        out.append({
            "id": p["id"], "name": p["name"], "type": "static", "unblock": True,
            "available": available,
            "reason": None if available else
            _tr('msg.modules.hosts.static_providers.the_zapret_discord_youtube_submodule_was_not_fou'),
        })
    return out


def get(provider_id: str) -> dict:
    """Внутренний дескриптор (с Path) — для manager.py. Неизвестный id — KeyError."""
    for p in _STATIC:
        if p["id"] == provider_id:
            return p
    raise ChimeraKeyError('err.hosts.static_providers.static_provider_was_not_found', p0=f'{provider_id!r}')


def read_entries(provider_id: str) -> list[dict]:
    """Читает и парсит файл заново — актуально на момент вызова.

    Нет файла (не найден сабмодуль) — FileNotFoundError с понятной причиной,
    ловится вызывающим кодом (manager._sync) как «провайдер недоступен».
    """
    p = get(provider_id)
    if not p["path"].exists():
        raise ChimeraFileNotFoundError('err.hosts.static_providers.file_not_found_the_zapret_discord_youtube_submod', p0=p['name'], p1=p['path'])
    text = p["path"].read_text(encoding="utf-8", errors="replace")
    return parse_hosts_text(text)
