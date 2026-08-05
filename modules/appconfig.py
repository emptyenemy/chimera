"""Чтение/запись config.json приложения — единый источник для main и UI."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
DEFAULTS = {"interface": "ui", "auto_elevate": True, "ui_backend": "pyside6"}


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
    data = load()
    data[key] = value
    _write(data)
    return data
