"""Game-фильтр и IPSet-фильтр — настройки запуска winws2 (портированы с Flowseal service.bat).

Game-фильтр: расширяет перехват на «игровые» высокие порты (по умолчанию 1024-65535,
диапазон настраиваемый) и добавляет профиль десинка по ним (для игр трафик не TLS/QUIC,
а произвольный по случайным портам). Хранится в config.json: "game_filter" = off|all|tcp|udp,
"game_filter_tcp"/"game_filter_udp" — диапазоны портов (формат и границы — как у Flowseal
:validate_game_filter_range). Выкл = порт-заглушка 12.

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

from modules.i18n import t as _tr

from modules.errors import ChimeraFileNotFoundError, ChimeraRuntimeError, ChimeraValueError

import hashlib
import re
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
GAME_RANGE_DEFAULT = "1024-65535"

# Один элемент диапазона: порт (без ведущего нуля, до 5 цифр) или "порт-порт".
# Как у Flowseal (:gf_validate_item) — findstr /r /x /c:"[1-9][0-9]*" /c:"[1-9][0-9]*-[1-9][0-9]*"
# плюс проверка длины (!Start:~5,1! пусто -> не больше 5 цифр).
_GAME_RANGE_ITEM_RE = re.compile(r"^[1-9][0-9]{0,4}(-[1-9][0-9]{0,4})?$")


def game_mode() -> str:
    m = appconfig.load().get("game_filter", "off")
    return m if m in GAME_MODES else "off"


def set_game_mode(mode: str) -> str:
    if mode not in GAME_MODES:
        raise ChimeraValueError('err.winws.filters.game_filter_mode_off_all_tcp_udp')
    appconfig.set_value("game_filter", mode)
    return mode


def validate_game_range(value: str) -> str:
    """Диапазон(ы) портов game-фильтра — как :validate_game_filter_range у Flowseal:
    список через запятую, элемент — порт или "порт-порт", без пробелов и ведущих
    нулей, 1..65535, начало не больше конца. Возвращает нормализованную строку
    (без пробелов) либо бросает ValueError с описанием, что не так."""
    s = "".join(str(value).split())
    if not s:
        raise ChimeraValueError('err.winws.filters.the_port_range_cannot_be_empty')
    for item in s.split(","):
        m = _GAME_RANGE_ITEM_RE.match(item)
        if not m:
            raise ChimeraValueError('err.winws.filters.invalid_port_range_example_1024_1934_1936_65535', p0=f'{item!r}')
        start_s, _, end_s = item.partition("-")
        start, end = int(start_s), int(end_s or start_s)
        if start > 65535 or end > 65535:
            raise ChimeraValueError('err.winws.filters.port_outside_the_range_1_65535', p0=f'{item!r}')
        if start > end:
            raise ChimeraValueError('err.winws.filters.range_start_is_greater_than_its_end', p0=f'{item!r}')
    return s


def _stored_range(key: str) -> str:
    """Диапазон из config.json с фолбэком на дефолт — как game_mode() для битого
    значения (например, руками подпорченный config.json)."""
    value = appconfig.load().get(key, GAME_RANGE_DEFAULT)
    try:
        return validate_game_range(str(value))
    except ValueError:
        return GAME_RANGE_DEFAULT


def game_ranges() -> dict:
    """{'tcp': диапазон, 'udp': диапазон} — независимо от текущего режима."""
    return {"tcp": _stored_range("game_filter_tcp"), "udp": _stored_range("game_filter_udp")}


def set_game_ranges(tcp: str | None = None, udp: str | None = None) -> dict:
    """Сохраняет диапазон(ы). None — соответствующий диапазон не трогаем (задан
    только tcp или только udp)."""
    if tcp is not None:
        appconfig.set_value("game_filter_tcp", validate_game_range(tcp))
    if udp is not None:
        appconfig.set_value("game_filter_udp", validate_game_range(udp))
    return game_ranges()


def game_ports(mode: str | None = None) -> dict | None:
    """{'tcp': ports|None, 'udp': ports|None} для game-профиля, или None если выключен."""
    mode = mode or game_mode()
    if mode == "off":
        return None
    ranges = game_ranges()
    return {
        "tcp": ranges["tcp"] if mode in ("all", "tcp") else None,
        "udp": ranges["udp"] if mode in ("all", "udp") else None,
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
        raise ChimeraValueError('err.winws.filters.ipset_state_any_none_loaded')
    cur = ipset_state()
    if mode == "loaded":
        if cur == "loaded":
            pass  # уже загружен
        elif IPSET_BACKUP.exists():
            shutil.copyfile(IPSET_BACKUP, IPSET_FILE)
        else:
            raise ChimeraFileNotFoundError('err.winws.filters.no_saved_list_click_update_list_first')
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
        raise ChimeraRuntimeError('err.winws.filters.the_downloaded_list_is_empty')
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
    (winws2 читает блоб один раз при старте — запущенную стратегию перезапускает Api.fake_set)."""
    if slot not in FAKE_SLOTS:
        raise ValueError(_tr('msg.modules.winws.filters.fake_slot_s') % " / ".join(FAKE_SLOTS))
    src = ASSETS_DIR / ("%s.bin" % name)
    if name.startswith(ACTIVE_PREFIX) or not src.exists():
        raise FileNotFoundError(_tr('msg.modules.winws.filters.no_such_blob_s') % name)
    shutil.copyfile(src, ASSETS_DIR / FAKE_SLOTS[slot][0])
    return fakes_state()


def state() -> dict:
    """Сводка для UI."""
    return {
        "game": game_mode(),
        "game_ranges": game_ranges(),
        "ipset": ipset_state(),
        "ipset_count": ipset_count(),
        "ipset_stored": ipset_stored(),
        "fakes": fakes_state(),
    }
