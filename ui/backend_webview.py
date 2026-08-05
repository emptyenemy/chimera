"""Бэкенд окна на pywebview (на Windows — системный Edge WebView2), мост — js_api.

Легче PySide6 (не тащит свой Chromium, окно стартует заметно быстрее), но зависит
от установленного в системе WebView2 и требует ручных --add-data при упаковке —
поэтому сборка (build.bat) идёт на PySide6, см. ui/backend_qt.py.
"""

import json

import webview

from .api import WEB_DIR, Api


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
    api = Api()
    window = webview.create_window(
        "CHIMERA",
        str(WEB_DIR / "index.html"),
        js_api=JsApi(api),
        width=1080,
        height=720,
        min_size=(860, 560),
        background_color="#16161e",
    )
    api.push = lambda fn, payload: window.evaluate_js(
        f"window.{fn} && window.{fn}({json.dumps(payload)})"
    )
    window.events.closing += api.shutdown
    webview.start()
