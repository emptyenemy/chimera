"""Чьи это сети: адрес из диапазонов Cloudflare (встроенный список lists/cloudflare.txt).

Большая часть сайтов, которые не открываются, стоит за Cloudflare. Проверка помечает такие
адреса, и страница предлагает пустить через прокси весь Cloudflare разом, а не каждый сайт.
Список читается заново, только когда файл поменялся: проверка зовёт это на каждый домен.
Две правки подряд могут получить одну метку времени, поэтому сверяются ещё размер и индекс
файла — запись списка подменяет файл целиком, и индекс у нового свой.
"""

import ipaddress

from modules import domains

CLOUDFLARE_LIST = "cloudflare"

_cache: dict = {"stamp": None, "nets": ()}


def _cloudflare_nets() -> tuple:
    path = domains.LISTS_DIR / f"{CLOUDFLARE_LIST}.txt"
    try:
        info = path.stat()
    except OSError:
        return ()
    stamp = (str(path), info.st_mtime_ns, info.st_size, info.st_ino)
    if _cache["stamp"] != stamp:
        nets = (domains.as_network(entry) for entry in domains.load_list(CLOUDFLARE_LIST))
        _cache.update(stamp=stamp, nets=tuple(n for n in nets if n is not None))
    return _cache["nets"]


def provider(ip) -> str | None:
    """"cloudflare", если адрес из его сетей; иначе None (и для пустого или кривого адреса)."""
    try:
        addr = ipaddress.ip_address(ip)
    except (TypeError, ValueError):
        return None
    if any(addr.version == net.version and addr in net for net in _cloudflare_nets()):
        return CLOUDFLARE_LIST
    return None
