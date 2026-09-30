"""Бэкенд окна на pywebview (на Windows — системный Edge WebView2), мост — js_api.

Легче PySide6 (не тащит свой Chromium, окно стартует заметно быстрее), но зависит
от установленного в системе WebView2 и требует ручных --add-data при упаковке —
поэтому сборка (build.bat) идёт на PySide6, см. ui/backend_qt.py.
"""

import json
import os
import sys
import secrets
import threading
from http.server import ThreadingHTTPServer

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


def _asset_server(api):
    from ui.backend_browser import _Handler, _Hub

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.api, server.hub, server.token = api, _Hub(), secrets.token_urlsafe(32)
    server.web_dir, server.missing_next, server.native_bridge = web_dir(), False, True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/?t={server.token}"


def run():
    from modules import control, instance
    from ui.tray_win32 import Tray, close_to_tray

    smoke_port = os.environ.get("QTWEBENGINE_REMOTE_DEBUGGING") if os.environ.get("CHIMERA_SMOKE") == "1" else None
    if smoke_port:
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(smoke_port)
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False

    api = Api()
    quitting = False
    hidden = "--tray" in sys.argv and sys.platform == "win32"
    # Serve the normal assets with the Python boot script inserted before CSS/JS.
    server, url = _asset_server(api)
    window = webview.create_window(
        "Chimera", url, js_api=JsApi(api),
        width=1080, height=720, min_size=(860, 560),
        background_color=theme.window_bg(), hidden=hidden,
    )
    api.push = lambda fn, payload: window.evaluate_js(
        f"window.{fn} && window.{fn}({json.dumps(payload)})"
    )

    def background_changed(color):
        if sys.platform != "win32" or window.native is None:
            return
        from System import Action
        from System.Drawing import ColorTranslator

        def update():
            native_color = ColorTranslator.FromHtml(color)
            window.native.BackColor = native_color
            window.native.browser.webview.DefaultBackgroundColor = native_color

        window.native.BeginInvoke(Action(update))

    api._native_theme_changed = background_changed

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

    cleaned = False

    def cleanup():
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        if listener:
            listener.close()
        if tray:
            tray.close()
        server.shutdown()
        server.server_close()
        api.shutdown()

    window.events.closing += closing
    window.events.closed += cleanup
    if hidden and not (tray and tray.available):
        window.events.loaded += show
    try:
        webview.start(gui="edgechromium" if sys.platform == "win32" else None, debug=bool(smoke_port))
    finally:
        cleanup()
