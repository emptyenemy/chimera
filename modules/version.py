"""Версия программы и сравнение версий.

VERSION в репозитории — "dev": запуск из исходников — всегда разработческая
версия, самообновление в ней выключено (modules/selfupdate.py). Настоящую
версию подставляет CI из тега перед сборкой: tools/set_version.py v0.2.0.

Сравнение — semver с пре-релизами: 0.3.0-beta.1 < 0.3.0-beta.2 < 0.3.0.
"""

import re

VERSION = "dev"

_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def parse(v: str) -> tuple | None:
    """Ключ сравнения версии; None — не версия (dev, мусор)."""
    m = _RE.match((v or "").strip())
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    if pre is None:
        tail = (1,)  # релиз старше любого своего пре-релиза
    else:
        # части пре-релиза: числа сравниваются числами, слова — строками,
        # и число младше слова (как в semver)
        tail = (0, *((0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in pre.split(".")))
    return int(major), int(minor), int(patch), tail


def is_newer(latest: str, current: str) -> bool:
    """Новее ли latest, чем current. Неразборчивая current (dev) — любая версия новее."""
    new = parse(latest)
    if new is None:
        return False
    cur = parse(current)
    return cur is None or new > cur


def file_version(v: str) -> str:
    """Четырёхчастная версия для свойств exe: 0.3.0-beta.1 → 0.3.0.1, 0.3.0 → 0.3.0.0."""
    m = _RE.match((v or "").strip())
    if not m:
        return "0.0.0.0"
    major, minor, patch, pre = m.groups()
    build = 0
    if pre:
        nums = re.findall(r"\d+", pre)
        build = int(nums[-1]) if nums else 0
    return f"{major}.{minor}.{patch}.{build}"
