"""Бэкенд окна на pywebview (на Windows — системный Edge WebView2), мост — js_api.

Легче PySide6 (не тащит свой Chromium, окно стартует заметно быстрее), но зависит
от установленного в системе WebView2 и требует ручных --add-data при упаковке —
поэтому сборка (build.bat) идёт на PySide6, см. ui/backend_qt.py.
"""

import json
import sys

import webview

from . import theme
from .api import Api
from .frontend import web_dir


class JsApi:
    """Та же единая точка входа, что и Bridge.call у Qt, — один метод на все ~60.

    Своего пула тут нет: pywebview исполняет каждый вызов js_api в отдельном
    потоке и сам резолвит промис на стороне JS, поток UI не блокируется.
    """

    def __init__(self, api: Api):
        self._api = api

    def call(self, method: str, args_json: str) -> str:
        return self._api.dispatch(method, args_json)


def run():
    from modules import control, instance
    from ui.tray_win32 import Tray, close_to_tray

    api = Api()
    quitting = False
    hidden = "--tray" in sys.argv and sys.platform == "win32"
    window = webview.create_window(
        "Chimera", str(web_dir() / "index.html"), js_api=JsApi(api),
        width=1080, height=720, min_size=(860, 560),
        background_color=theme.window_bg(), hidden=hidden,
    )
    api.push = lambda fn, payload: window.evaluate_js(
        f"window.{fn} && window.{fn}({json.dumps(payload)})"
    )

    def show():
        window.show()
        window.restore()

    def quit_app():
        nonlocal quitting
        quitting = True
        window.destroy()

    tray = Tray(api, show, quit_app) if sys.platform == "win32" else None
    listener = instance.listen(show)
    api.request_quit = quit_app
    control.start_for(api)

    def closing():
        if not quitting and close_to_tray(tray):
            window.hide()
            return False
        return True

    def cleanup():
        if listener:
            listener.close()
        if tray:
            tray.close()
        api.shutdown()

    window.events.closing += closing
    window.events.closed += cleanup
    if hidden and not (tray and tray.available):
        window.events.loaded += show
    try:
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)
    finally:
        cleanup()
