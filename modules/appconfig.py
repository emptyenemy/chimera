"""Чтение/запись config.json приложения — единый источник для main и UI."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
# close_to_tray — крестик окна прячет его в трей (движок pyside6), а не закрывает программу;
# update_channel — stable | beta (пре-релизы), update_check — проверять обновления в фоне;
# theme — оформление окна: system (как в Windows) | light | dark (см. ui/theme.py)
THEMES = ("system", "light", "dark")
DEFAULTS = {"interface": "ui", "auto_elevate": True, "ui_backend": "pyside6", "close_to_tray": True,
            "update_channel": "stable", "update_check": True, "theme": "system"}


def load() -> dict:
    """Конфиг с подставленными дефолтами. Битый JSON → дефолты."""
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError):
            pass
    return data


def _write(data: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )


def set_value(key: str, value) -> dict:
    """Меняет одну настройку и сразу пишет файл. Возвращает полный конфиг."""
    if key == "theme" and (not isinstance(value, str) or value not in THEMES):
        raise ValueError(f"Тема {value!r} неизвестна. Доступные: {', '.join(THEMES)}.")
    data = load()
    data[key] = value
    _write(data)
    return data
