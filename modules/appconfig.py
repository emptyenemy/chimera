"""Чтение/запись config.json приложения — единый источник для main и UI."""

import json
import threading
from pathlib import Path

from modules import appearance, i18n
from modules.errors import ChimeraValueError
from modules.fileutil import atomic_write_text
from modules.version import default_backend

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_WRITE_LOCK = threading.RLock()
# close_to_tray — крестик окна прячет его в трей (движок pyside6), а не закрывает программу;
# update_channel — stable | beta (пре-релизы), update_check — проверять обновления в фоне;
# theme — оформление окна: system (как в Windows) | light | dark (см. ui/theme.py);
# lang — язык программы: auto (как в Windows) | ru | en (см. modules/i18n.py);
# autotune_watch — самолечение в фоне: чинить сервисы, которые автонастройка уже чинила (docs/AUTOTUNE.md);
# autotune_steps — какими способами подбирать (стратегии, hosts, DNS, прокси), autotune_exclude —
# какие варианты не пробовать вовсе: {"dns": ["google"], "hosts": [...], "strategy": [...]}
THEMES = ("system", "light", "dark")
DEFAULTS = {"interface": "ui", "auto_elevate": False, "ui_backend": default_backend(), "close_to_tray": True,
            "update_channel": "stable", "update_check": True, "theme": "system", "lang": "auto",
            "appearance": dict(appearance.DEFAULTS), "appearance_custom": None, "providers_hidden": [],
            "autotune_watch": False, "autotune_steps": ["strategy", "hosts", "dns", "proxy"],
            "autotune_exclude": {}}


def load() -> dict:
    """Конфиг с подставленными дефолтами. Битый JSON → дефолты."""
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update(stored)
        except (OSError, ValueError):
            pass
    data["appearance"] = appearance.normalize_settings(data.get("appearance", {}), fallback=True)
    data["appearance_custom"] = appearance.normalize_custom(data.get("appearance_custom"), fallback=True)
    return data


def _write(data: dict) -> None:
    atomic_write_text(CONFIG_PATH, json.dumps(data, ensure_ascii=False, indent=4) + "\n")


def restore_values(values: dict) -> dict:
    from modules.configbackups import normalize
    target = normalize("config", values)
    with _WRITE_LOCK:
        _write(target)
        i18n.refresh()
    return target


def set_value(key: str, value) -> dict:
    """Меняет одну настройку и сразу пишет файл. Возвращает полный конфиг."""
    return set_values({key: value})


def set_values(values: dict) -> dict:
    """Проверяет все значения и сохраняет связанные настройки одной записью."""
    normalized = {key: _normalize_value(key, value) for key, value in values.items()}
    with _WRITE_LOCK:
        data = load()
        if normalized:
            data.update(normalized)
            _write(data)
            if "lang" in normalized:
                i18n.refresh()
        return data


def _autotune_steps(value) -> list:
    from modules.autotune.engine import STEPS
    if (not isinstance(value, list) or not value or len(set(value)) != len(value)
            or not all(isinstance(s, str) and s in STEPS for s in value)):
        raise ChimeraValueError("err.config.autotune_steps", options=", ".join(STEPS))
    return [s for s in STEPS if s in value]


def _autotune_exclude(value) -> dict:
    # прокси один на всех — его выключают шагом, а не вариантом
    if not isinstance(value, dict) or set(value) - {"strategy", "hosts", "dns"}:
        raise ChimeraValueError("err.config.autotune_exclude")
    for ids in value.values():
        if (not isinstance(ids, list) or len(ids) > 200
                or not all(isinstance(i, str) and 0 < len(i) <= 64 for i in ids)):
            raise ChimeraValueError("err.config.autotune_exclude")
    return {step: list(dict.fromkeys(ids)) for step, ids in value.items() if ids}


def _normalize_value(key: str, value):
    if key == "theme" and (not isinstance(value, str) or value not in THEMES):
        raise ChimeraValueError("err.config.theme_unknown", value=repr(value), options=", ".join(THEMES))
    if key == "lang" and (not isinstance(value, str) or value not in i18n.SETTINGS):
        raise ChimeraValueError("err.config.lang_unknown", value=repr(value), options=", ".join(i18n.SETTINGS))
    if key == "appearance_custom":
        value = appearance.normalize_custom(value)
    if key == "appearance":
        value = appearance.normalize_settings(value)
    if key == "autotune_watch" and not isinstance(value, bool):
        raise ChimeraValueError("err.appearance.settings")
    if key == "autotune_steps":
        value = _autotune_steps(value)
    if key == "autotune_exclude":
        value = _autotune_exclude(value)
    if key == "providers_hidden" and (not isinstance(value, list) or len(value) > 200
                                or not all(isinstance(i, str) and i for i in value)):
        raise ChimeraValueError("err.appearance.settings")
    allowed = set(DEFAULTS) | {"ui_port", "tray_hint_shown", "dns_probe", "game_filter", "game_filter_tcp", "game_filter_udp"}
    if key not in allowed:
        raise ChimeraValueError("err.appearance.settings")
    return value
