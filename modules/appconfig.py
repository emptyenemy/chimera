"""Чтение/запись config.json приложения — единый источник для main и UI."""

import json
from pathlib import Path

from modules import appearance, i18n
from modules.errors import ChimeraValueError
from modules.fileutil import atomic_write_text
from modules.version import default_backend

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
# close_to_tray — крестик окна прячет его в трей (движок pyside6), а не закрывает программу;
# update_channel — stable | beta (пре-релизы), update_check — проверять обновления в фоне;
# theme — оформление окна: system (как в Windows) | light | dark (см. ui/theme.py);
# lang — язык программы: auto (как в Windows) | ru | en (см. modules/i18n.py)
THEMES = ("system", "light", "dark")
DEFAULTS = {"interface": "ui", "auto_elevate": False, "ui_backend": default_backend(), "close_to_tray": True,
            "update_channel": "stable", "update_check": True, "theme": "system", "lang": "auto",
            "appearance": dict(appearance.DEFAULTS), "appearance_custom": None}


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
    _write(target)
    i18n.refresh()
    return target


def set_value(key: str, value) -> dict:
    """Меняет одну настройку и сразу пишет файл. Возвращает полный конфиг."""
    if key == "theme" and (not isinstance(value, str) or value not in THEMES):
        raise ChimeraValueError("err.config.theme_unknown", value=repr(value), options=", ".join(THEMES))
    if key == "lang" and (not isinstance(value, str) or value not in i18n.SETTINGS):
        raise ChimeraValueError("err.config.lang_unknown", value=repr(value), options=", ".join(i18n.SETTINGS))
    if key == "appearance_custom":
        value = appearance.normalize_custom(value)
    if key == "appearance":
        value = appearance.normalize_settings(value)
    allowed = set(DEFAULTS) | {"ui_port", "tray_hint_shown", "dns_probe", "game_filter", "game_filter_tcp", "game_filter_udp"}
    if key not in allowed:
        raise ChimeraValueError("err.appearance.settings")
    data = load()
    data[key] = value
    _write(data)
    if key == "lang":
        i18n.refresh()
    return data
