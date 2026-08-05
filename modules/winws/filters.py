"""Game-фильтр и IPSet-фильтр — настройки запуска winws2 (портированы с Flowseal service.bat).

Game-фильтр: расширяет перехват на «игровые» высокие порты (1024-65535) и добавляет
профиль десинка по ним (для игр трафик не TLS/QUIC, а произвольный по случайным портам).
Хранится в config.json: "game_filter" = off|all|tcp|udp. Выкл = порт-заглушка 12.

IPSet-фильтр: состояние файла strategies/hostlists/ipset-all.txt (его используют
fallback-профили «по IP»):
  none   — заглушка 203.0.113.113/32 (ни по чему не бьёт; дефолт);
  any    — пустой файл (без ограничения по IP);
  loaded — реальный список подсетей (качается из репо Flowseal).
Переключение loaded<->none<->any с бэкапом загруженного списка в .backup.

Fake replace: ACTIVE_DISCORD_UDP.bin и ACTIVE_GAME_UDP.bin — не блобы, а СЛОТЫ.
Стратегии ссылаются только на них, а какой именно фейк лежит внутри — выбор
пользователя (у разных провайдеров проходят разные). Выбранный кандидат просто
копируется в файл слота, текущий определяется сравнением SHA256 — ровно так же,
как в service.bat Flowseal (:replace_active_fakes).
"""

import hashlib
import shutil
import urllib.request
from pathlib import Path

from modules import appconfig

STRATEGIES_DIR = Path(__file__).parent.parent.parent / "strategies"
HOSTLISTS_DIR = STRATEGIES_DIR / "hostlists"
IPSET_FILE = HOSTLISTS_DIR / "ipset-all.txt"
IPSET_BACKUP = HOSTLISTS_DIR / "ipset-all.txt.backup"
IPSET_PLACEHOLDER = "203.0.113.113/32"
IPSET_URL = (
    "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube"
    "/refs/heads/main/.service/ipset-service.txt"
)

# --- game filter ---------------------------------------------------------------

GAME_MODES = ("off", "all", "tcp", "udp")
_GAME_RANGE = "1024-65535"


def game_mode() -> str:
    m = appconfig.load().get("game_filter", "off")
    return m if m in GAME_MODES else "off"


def set_game_mode(mode: str) -> str:
    if mode not in GAME_MODES:
        raise ValueError("Режим game-фильтра: off / all / tcp / udp")
    appconfig.set_value("game_filter", mode)
    return mode


def game_ports(mode: str | None = None) -> dict | None:
    """{'tcp': ports|None, 'udp': ports|None} для game-профиля, или None если выключен."""
    mode = mode or game_mode()
    if mode == "off":
        return None
    return {
        "tcp": _GAME_RANGE if mode in ("all", "tcp") else None,
        "udp": _GAME_RANGE if mode in ("all", "udp") else None,
    }


# --- ipset filter --------------------------------------------------------------

IPSET_STATES = ("any", "none", "loaded")


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _ipset_lines() -> list[str]:
    return _lines(IPSET_FILE)


def _count(lines: list[str]) -> int:
    """Реальные подсети без заглушки."""
    return sum(1 for ln in lines if ln != IPSET_PLACEHOLDER)


def ipset_state() -> str:
    lines = _ipset_lines()
    if not lines:
        return "any"
    if lines == [IPSET_PLACEHOLDER]:
        return "none"
    return "loaded"


def ipset_count() -> int:
    """Подсети в АКТИВНОМ списке (что реально применяется)."""
    return _count(_ipset_lines())


def ipset_stored() -> int:
    """Подсети в сохранённой копии (запас, готовый к активации через «Список»)."""
    return _count(_lines(IPSET_BACKUP))


def set_ipset_mode(mode: str) -> dict:
    if mode not in IPSET_STATES:
        raise ValueError("Состояние IPSet: any / none / loaded")
    cur = ipset_state()
    if mode == "loaded":
        if cur == "loaded":
            pass  # уже загружен
        elif IPSET_BACKUP.exists():
            shutil.copyfile(IPSET_BACKUP, IPSET_FILE)
        else:
            raise FileNotFoundError("Нет сохранённого списка — сначала нажми «Обновить список».")
    else:
        if cur == "loaded":  # уходим с реального списка — сохраним его
            shutil.copyfile(IPSET_FILE, IPSET_BACKUP)
        IPSET_FILE.write_text(
            (IPSET_PLACEHOLDER + "\n") if mode == "none" else "", encoding="utf-8"
        )
    return ipset_status()


def update_ipset() -> dict:
    """Качает ipset из репо Flowseal в СОХРАНЁННУЮ копию (запас).

    Режим фильтра НЕ меняет: если выбрано «Нет»/«Любой IP» — так и остаётся, список
    просто лежит готовым к активации. Активный файл трогаем, только если уже выбран
    «Список» (loaded) — тогда обновляем и его.
    """
    req = urllib.request.Request(IPSET_URL, headers={"User-Agent": "chimera"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read().decode("utf-8", "replace")
    lines = [ln.strip() for ln in data.splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("Скачанный список пуст")
    text = "\n".join(lines) + "\n"
    IPSET_BACKUP.write_text(text, encoding="utf-8")          # всегда — в запас
    if ipset_state() == "loaded":                            # активен «Список» — освежим
        IPSET_FILE.write_text(text, encoding="utf-8")
    return {**ipset_status(), "downloaded": len(lines)}


def ipset_status() -> dict:
    return {"state": ipset_state(), "count": ipset_count(), "stored": ipset_stored()}


# --- fake replace (ACTIVE_*-слоты) ----------------------------------------------

ASSETS_DIR = STRATEGIES_DIR / "assets"
ACTIVE_PREFIX = "ACTIVE_"
FAKE_SLOTS = {
    "discord": ("ACTIVE_DISCORD_UDP.bin", "Discord UDP"),
    "game": ("ACTIVE_GAME_UDP.bin", "GameFilter UDP"),
}


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_candidates() -> list[str]:
    """Блобы-кандидаты (имена без .bin) — всё в assets, кроме самих слотов."""
    return sorted(p.stem for p in ASSETS_DIR.glob("*.bin")
                  if not p.name.startswith(ACTIVE_PREFIX))


def fakes_state() -> dict:
    """{slot: имя кандидата в слоте или None} + список кандидатов.

    None означает «в слоте лежит блоб, которого нет среди кандидатов» — например
    файл подложили руками. Ровно как «(not found)» у Flowseal.
    """
    hashes = {p.stem: _sha256(p) for p in ASSETS_DIR.glob("*.bin")
              if not p.name.startswith(ACTIVE_PREFIX)}
    slots = {}
    for slot, (fname, label) in FAKE_SLOTS.items():
        active = _sha256(ASSETS_DIR / fname)
        current = next((n for n, h in hashes.items() if h and h == active), None)
        slots[slot] = {"label": label, "file": fname, "current": current,
                       "present": active is not None}
    return {"slots": slots, "candidates": fake_candidates()}


def set_fake(slot: str, name: str) -> dict:
    """Кладёт кандидата в слот. Применится при следующем запуске стратегии
    (winws2 читает блоб один раз при старте — перезапуск делает UI)."""
    if slot not in FAKE_SLOTS:
        raise ValueError("Слот фейка: %s" % " / ".join(FAKE_SLOTS))
    src = ASSETS_DIR / ("%s.bin" % name)
    if name.startswith(ACTIVE_PREFIX) or not src.exists():
        raise FileNotFoundError("Нет такого блоба: %s" % name)
    shutil.copyfile(src, ASSETS_DIR / FAKE_SLOTS[slot][0])
    return fakes_state()


def state() -> dict:
    """Сводка для UI."""
    return {
        "game": game_mode(),
        "ipset": ipset_state(),
        "ipset_count": ipset_count(),
        "ipset_stored": ipset_stored(),
        "fakes": fakes_state(),
    }
