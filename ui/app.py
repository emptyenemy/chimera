"""UI-режим: выбор оконного движка (config.json -> ui_backend) и запуск окна.

Логика и все методы, доступные фронтенду, — в ui/api.py, движки — в
ui/backend_qt.py (PySide6/QWebEngineView) и ui/backend_webview.py (pywebview).
Фронтенд (ui/web) один и тот же: мост он определяет сам, см. initBridge().
"""

from modules.i18n import t as _tr

from modules.version import default_backend

BACKENDS = {
    "pyside6": ("ui.backend_qt", "PySide6"),
    "pywebview": ("ui.backend_webview", "pywebview"),
    "browser": ("ui.backend_browser", _tr('msg.ui.app.standard_library')),
}
DEFAULT_BACKEND = default_backend()  # тот, на котором собирается exe (см. build.bat)
FALLBACK_BACKEND = "browser"  # без своих зависимостей — работает всегда


def _load(name: str):
    import importlib
    return importlib.import_module(BACKENDS[name][0])


def run(backend_name: str | None = None):
    """backend_name — движок, заданный флагом запуска (--browser); иначе из config.json."""
    from modules import appconfig

    name = str(backend_name or appconfig.load().get("ui_backend") or DEFAULT_BACKEND).lower()
    if name not in BACKENDS:
        print(_tr('msg.ui.app.unknown_window_engine_available_using', p0=f'{name!r}', p1=f"{', '.join(BACKENDS)}", p2=f'{DEFAULT_BACKEND}'))
        name = DEFAULT_BACKEND

    from modules import paths
    from modules.version import FLAVOR
    if paths.IS_FROZEN and name != "browser" and name != default_backend(FLAVOR):
        name = default_backend(FLAVOR)
    if name == "pywebview":
        from ui.webview_runtime import installed
        if not installed():
            print(_tr('msg.ui.app.webview2_runtime_is_not_installed_opening_the_in'))
            name = "browser"
    try:
        backend = _load(name)
    except ImportError as e:
        # движок выбран, но пакета нет — не падаем, а уходим на браузерный:
        # ему ставить нечего, так что эта ветка всегда чем-то заканчивается
        other = FALLBACK_BACKEND if name != FALLBACK_BACKEND else DEFAULT_BACKEND
        print(_tr('msg.ui.app.engine_is_unavailable_not_installed_trying', p0=f'{name}', p1=f'{BACKENDS[name][1]}', p2=f'{e}', p3=f'{other}'))
        backend = _load(other)

    backend.run()
