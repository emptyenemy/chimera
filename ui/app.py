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
FALLBACK_BACKEND = "browser"


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
    available = {"qt": ("pyside6", "browser"), "webview": ("pywebview", "browser"),
                 "lite": ("browser", "pywebview")}[FLAVOR] if paths.IS_FROZEN else tuple(BACKENDS)
    if name not in available:
        name = available[0]
    candidates = [name, *(other for other in ("browser", "pywebview", "pyside6") if other in available and other != name)]
    error = None
    for candidate in candidates:
        try:
            if candidate == "pywebview":
                from ui.webview_runtime import bundled, installed
                if bundled() is None and not installed():
                    raise RuntimeError("WebView2 is unavailable")
            _load(candidate).run()
            return
        except Exception as failure:
            from ui.startup import log_failure
            log_failure(candidate, failure)
            error = failure
    raise RuntimeError("No window engine could open Chimera") from error
