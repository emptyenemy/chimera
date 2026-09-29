"""«Записать домены сайта»: какие домены понадобились сайту.

Сайт не открывается, а какие домены ему нужны (CDN, API, картинки), неизвестно. Пока
идёт запись, пользователь открывает сайт, а мы сравниваем кэш DNS Windows до и после:
разница — имена, которые запрашивались за это время. Группируем по основному домену,
очевидные трекеры помечаем — в список их по умолчанию не добавляют.

Ограничение: видно только то, что прошло через системный резолвер. Браузеры с DNS через
HTTPS (защищённый DNS) спрашивают имена мимо кэша Windows, и часть доменов не покажется.
"""

from modules.i18n import t as _tr

from modules.errors import ChimeraRuntimeError

import ipaddress
import json
import subprocess

_NO_WINDOW = 0x08000000

# составные суффиксы, у которых «основной домен» — три метки (shop.co.uk), а не две
_SECOND_LEVEL = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "com.au", "net.au", "org.au", "co.jp", "or.jp",
    "co.nz", "com.br", "com.tr", "com.cn", "com.ua", "com.mx", "com.ar", "co.in", "co.za", "co.kr",
})
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".localdomain", ".arpa", ".corp", ".intranet")

# признаки трекеров и рекламы: домен, все имена которого подходят, помечается
_TRACKER_HINTS = (
    "doubleclick", "analytics", "metrics", "metrika", "telemetry", "adservice", "googlesyndication",
    "googletagmanager", "googleadservices", "scorecardresearch", "hotjar", "mixpanel", "segment.io",
    "sentry.io", "adsystem", "tracking", "appsflyer", "adjust.com", "mc.yandex", "an.yandex",
    "criteo", "taboola", "outbrain",
)


def _normalize(name) -> str:
    return str(name or "").strip().lower().rstrip(".")


def registrable(name) -> str | None:
    """Основной домен имени (example.com для cdn.example.com); None — это не сайт:
    локальное имя, IP, обратный запрос, служебная запись."""
    n = _normalize(name)
    if not n or "." not in n:
        return None
    try:
        ipaddress.ip_address(n)
        return None
    except ValueError:
        pass
    if n.endswith(_LOCAL_SUFFIXES) or n == "wpad" or n.startswith("wpad."):
        return None
    labels = n.split(".")
    if any(not lb or lb.startswith("_") for lb in labels):
        return None
    if ".".join(labels[-2:]) in _SECOND_LEVEL:
        return ".".join(labels[-3:]) if len(labels) >= 3 else None
    return ".".join(labels[-2:])


def _is_tracker(name: str) -> bool:
    return any(h in name for h in _TRACKER_HINTS)


def suggest(before: set, after: set) -> list[dict]:
    """Новые за время записи имена, сгруппированные по основному домену:
    [{domain, hosts, tracker}] — сначала обычные сайты, затем трекеры."""
    old = {_normalize(x) for x in before}
    groups: dict[str, list[str]] = {}
    for raw in after:
        n = _normalize(raw)
        if n in old:
            continue
        dom = registrable(n)
        if dom:
            groups.setdefault(dom, []).append(n)
    out = [{"domain": d, "hosts": sorted(set(hosts)), "tracker": all(_is_tracker(h) for h in hosts)}
           for d, hosts in groups.items()]
    return sorted(out, key=lambda g: (g["tracker"], g["domain"]))


# --- кэш DNS Windows ---------------------------------------------------------------------------

# тип 12 — обратные запросы (PTR): не сайты
_READ_PS = ("Get-DnsClientCache | Where-Object { $_.Type -ne 12 } "
            "| Select-Object -ExpandProperty Entry | ConvertTo-Json -Compress")


def read_cache() -> set[str]:
    """Имена из кэша DNS. Только чтение."""
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _READ_PS],
                         capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or _tr('msg.modules.domainrec.could_not_read_the_dns_cache'))
    out = res.stdout.strip()
    data = json.loads(out) if out else []
    if isinstance(data, str):
        data = [data]
    return {_normalize(x) for x in data if isinstance(x, str) and _normalize(x)}


def flush() -> None:
    """Сбрасывает кэш DNS (нужны права администратора): иначе домены, которые уже были в
    кэше, при записи не покажутся."""
    res = subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=20, creationflags=_NO_WINDOW)
    if res.returncode != 0:
        raise ChimeraRuntimeError('err.domainrec.could_not_clear_the_dns_cache')
