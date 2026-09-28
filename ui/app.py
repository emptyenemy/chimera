"""UI-режим: выбор оконного движка (config.json -> ui_backend) и запуск окна.

Логика и все методы, доступные фронтенду, — в ui/api.py, движки — в
ui/backend_qt.py (PySide6/QWebEngineView) и ui/backend_webview.py (pywebview).
Фронтенд (ui/web) один и тот же: мост он определяет сам, см. initBridge().
"""

BACKENDS = {
    "pyside6": ("ui.backend_qt", "PySide6"),
    "pywebview": ("ui.backend_webview", "pywebview"),
    "browser": ("ui.backend_browser", "стандартная библиотека"),
}
DEFAULT_BACKEND = "pyside6"  # тот, на котором собирается exe (см. build.bat)
FALLBACK_BACKEND = "browser"  # без своих зависимостей — работает всегда


def _load(name: str):
    import importlib
    return importlib.import_module(BACKENDS[name][0])


def run(backend_name: str | None = None):
    """backend_name — движок, заданный флагом запуска (--browser); иначе из config.json."""
    from modules import appconfig

    name = str(backend_name or appconfig.load().get("ui_backend") or DEFAULT_BACKEND).lower()
    if name not in BACKENDS:
        print(f"Неизвестный движок окна: {name!r}. Доступно: {', '.join(BACKENDS)}. "
              f"Беру {DEFAULT_BACKEND}.")
        name = DEFAULT_BACKEND

    try:
        backend = _load(name)
    except ImportError as e:
        # движок выбран, но пакета нет — не падаем, а уходим на браузерный:
        # ему ставить нечего, так что эта ветка всегда чем-то заканчивается
        other = FALLBACK_BACKEND if name != FALLBACK_BACKEND else DEFAULT_BACKEND
        print(f"Движок {name} недоступен ({BACKENDS[name][1]} не установлен: {e}). "
              f"Пробую {other}.")
        backend = _load(other)

    backend.run()
