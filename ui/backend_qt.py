"""Бэкенд окна на PySide6/QWebEngineView (свой бандленный Chromium), мост — QWebChannel."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from .api import WEB_DIR, Api


class Bridge(QObject):
    """Асинхронный JSON-RPC поверх QWebChannel.

    call() ничего не возвращает и мгновенно отпускает поток UI: работа уходит в
    пул, ответ прилетает сигналом resolved(callId, resultJson), фронт резолвит по
    callId свой промис (см. ui/web/js/core.js). Синхронный слот с result=str короче,
    но QWebChannel исполняет слот в потоке объекта — то есть в потоке UI, и любой
    поход в сеть/subprocess (dns_state ~4 c, proxy_state ~1 c, опрос дашборда
    каждые 3 с) намертво фризил окно на всё время вызова.
    """

    resolved = Signal(str, str)  # (callId, resultJson) — ответ на call()
    pushed = Signal(str, str)    # (jsFnName, payloadJson) — стриминг из Api._push

    def __init__(self, api: Api):
        super().__init__()
        self.api = api
        # с запасом на параллельный опрос дашборда (4 вызова разом) + автопинги
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="chimera-api")
        api.push = lambda fn, payload: self.pushed.emit(fn, json.dumps(payload))

    @Slot(str, str, str)
    def call(self, call_id: str, method: str, args_json: str) -> None:
        self.pool.submit(self._run, call_id, method, args_json)

    def _run(self, call_id: str, method: str, args_json: str) -> None:
        # emit из потока пула безопасен: Qt сам маршализует доставку в поток UI
        self.resolved.emit(call_id, self.api.dispatch(method, args_json))


def run():
    app = QApplication(sys.argv)
    app.setApplicationName("CHIMERA")

    api = Api()
    bridge = Bridge(api)
    channel = QWebChannel()
    channel.registerObject("bridge", bridge)

    view = QWebEngineView()
    view.page().setWebChannel(channel)
    view.page().setBackgroundColor("#16161e")
    view.load(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))

    window = QMainWindow()
    window.setWindowTitle("Chimera")
    window.setCentralWidget(view)
    window.resize(1080, 720)
    window.setMinimumSize(860, 560)

    def _on_closing():
        # невзятые вызовы отменяем и не ждём взятые: иначе висящий на выходе
        # запрос (проверка обновлений, скачивание ядра) держал бы процесс
        bridge.pool.shutdown(wait=False, cancel_futures=True)
        api.shutdown()

    app.aboutToQuit.connect(_on_closing)
    window.show()
    sys.exit(app.exec())
