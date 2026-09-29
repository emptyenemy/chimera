"""Бэкенд окна на PySide6/QWebEngineView (свой бандленный Chromium), мост — QWebChannel.

Плюс значок в трее: закрытие окна прячет его туда, а модули продолжают работать;
совсем программа закрывается через «Выход» в меню значка. С Windows (--tray)
стартует сразу в трей, без окна. Что показывает и умеет меню — ui/tray_model.py.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from modules import appconfig, control, instance

from . import theme, tray_model
from .api import Api
from .frontend import web_dir

# Иконка окна и панели задач. У собранного exe она и так зашита в ресурсы
# (build.bat), но при запуске из исходников без этого висела бы иконка python.exe.
APP_ICON = Path(__file__).resolve().parent.parent / "assets" / "logo" / "chimera.ico"


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


class MainWindow(QMainWindow):
    """Окно, которое по крестику прячется в трей, если трей есть и так настроено."""

    # показать окно — из любого потока (повторный запуск ловит поток modules/instance,
    # а трогать виджеты можно только из потока UI: сигнал доставит туда сам)
    show_requested = Signal()
    # закрыть программу совсем — тоже из любого потока (установка обновления идёт в пуле)
    quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self.tray = None  # Tray, если значок в трее поднялся
        self.show_requested.connect(self.bring_to_front)
        self.quit_requested.connect(self.quit_app)

    def quit_app(self):
        if self.tray:
            self.tray.icon.hide()  # иначе значок висит в трее до наведения мыши
        QApplication.quit()

    def bring_to_front(self):
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.tray and self.tray.hide_on_close():
            event.ignore()
            self.hide()
            self.tray.hint_once()
            return
        super().closeEvent(event)
        QApplication.quit()  # без трея (или по настройке) крестик — полный выход


class Tray(QObject):
    """Значок в трее: состояние защиты, переключатели модулей, «Открыть» и «Выход»."""

    notified = Signal(str, str)    # (заголовок, текст) — из потоков пула команд
    REFRESH_MS = 1500

    def __init__(self, app, window, api, bridge):
        super().__init__()
        self.app, self.window, self.api, self.bridge = app, window, api, bridge
        self.busy = set()  # модули, по которым команда ещё выполняется

        self.icon = QSystemTrayIcon(QIcon(str(APP_ICON)), app)
        self.icon.setToolTip("Chimera")  # только имя: состояние — в меню, не в подсказке
        menu = QMenu()
        menu.addAction("Открыть Chimera").triggered.connect(window.bring_to_front)
        menu.addSeparator()
        self.status = menu.addAction("")
        self.status.setEnabled(False)
        menu.addSeparator()
        self.toggles = {}
        for key, label in tray_model.MODULES:
            action = menu.addAction(label)
            action.setCheckable(True)
            # triggered (а не toggled) — только клик пользователя, не setChecked из refresh
            action.triggered.connect(lambda checked, k=key: self.toggle(k, checked))
            self.toggles[key] = action
        menu.addSeparator()
        self.panic_action = menu.addAction(tray_model.PANIC_LABEL)
        self.panic_action.triggered.connect(lambda: self.panic())
        menu.addSeparator()
        menu.addAction("Выход").triggered.connect(self.quit)
        menu.aboutToShow.connect(self.refresh)
        self.menu = menu  # иначе меню соберёт сборщик мусора
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)

        self.notified.connect(lambda title, text: self.icon.showMessage(
            title, text, QSystemTrayIcon.MessageIcon.Warning, 6000))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.REFRESH_MS)
        self.refresh()
        self.icon.show()

    # --- состояние ---------------------------------------------------------------

    def refresh(self):
        states = self.api.hub.snapshot()
        self.status.setText(tray_model.summary(states)[2])
        for key, action in self.toggles.items():
            action.setChecked(tray_model.is_on(key, states.get(key)))
            action.setEnabled(key not in self.busy)

    def toggle(self, key, on):
        try:
            method, args = tray_model.toggle_command(key, self.api.hub.snapshot().get(key), on)
        except ValueError as e:
            self.notified.emit("Chimera", str(e))
            self.refresh()
            return
        self.busy.add(key)
        self.refresh()
        self.bridge.pool.submit(self._run, key, method, args)

    def _run(self, key, method, args):
        # поток пула: старт winws/прокси — это секунды subprocess, UI не ждёт
        try:
            res = json.loads(self.api.dispatch(method, json.dumps(args)))
            if not res.get("ok"):
                label = dict(tray_model.MODULES)[key]
                self.notified.emit(f"{label}: не получилось", res.get("error") or "неизвестная ошибка")
        finally:
            self.busy.discard(key)

    def panic(self):
        # «Выключить всё» из меню: без подтверждения — пункт выбирают осознанно, а
        # включить обратно можно теми же переключателями
        self.busy.add("panic")
        self.panic_action.setEnabled(False)
        self.bridge.pool.submit(self._run_panic)

    def _run_panic(self):
        try:
            method, args = tray_model.PANIC_COMMAND
            res = json.loads(self.api.dispatch(method, json.dumps(args)))
            if not res.get("ok"):
                self.notified.emit("Выключить всё: не получилось", res.get("error") or "неизвестная ошибка")
                return
            text = tray_model.panic_summary(res.get("data"))
            if text:
                self.notified.emit("Выключить всё: не всё получилось", text)
        finally:
            self.busy.discard("panic")
            self.panic_action.setEnabled(True)

    # --- окно ----------------------------------------------------------------------

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.window.bring_to_front()

    def hide_on_close(self) -> bool:
        return bool(appconfig.load().get("close_to_tray", True))

    def hint_once(self):
        # первое сворачивание — объяснить, куда делось окно; дальше не надоедаем
        cfg = appconfig.load()
        if cfg.get("tray_hint_shown"):
            return
        appconfig.set_value("tray_hint_shown", True)
        self.icon.showMessage("Chimera работает в трее",
                              "Модули продолжают работать. Закрыть программу — «Выход» в меню значка.",
                              QSystemTrayIcon.MessageIcon.Information, 6000)

    def quit(self):
        self.icon.hide()
        self.app.quit()


def run():
    app = QApplication(sys.argv)
    app.setApplicationName("Chimera")
    app.setQuitOnLastWindowClosed(False)  # закрытое окно ≠ выход: программа живёт в трее
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))

    api = Api()
    bridge = Bridge(api)
    channel = QWebChannel()
    channel.registerObject("bridge", bridge)

    view = QWebEngineView()
    view.page().setWebChannel(channel)
    # тема — до первой отрисовки: скрипт на DocumentCreation ставит data-theme и класс dark
    mode = theme.resolve_theme()
    boot = QWebEngineScript()
    boot.setName("chimera-theme")
    boot.setSourceCode(theme.boot_script(mode))
    boot.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    boot.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    view.page().scripts().insert(boot)
    # пока страница грузится, окно залито этим цветом — он должен совпадать с фоном темы
    bg = theme.window_bg(mode)
    view.page().setBackgroundColor(QColor(bg))
    view.load(QUrl.fromLocalFile(str(web_dir() / "index.html")))

    window = MainWindow()
    window.setStyleSheet(f"QMainWindow {{ background: {bg}; }}")  # и до первой отрисовки страницы
    window.setWindowTitle("Chimera")
    window.setCentralWidget(view)
    window.resize(1080, 720)
    window.setMinimumSize(860, 560)

    tray = Tray(app, window, api, bridge) if QSystemTrayIcon.isSystemTrayAvailable() else None
    window.tray = tray
    # повторный запуск exe показывает это окно (см. modules/instance.py и main.py)
    listener = instance.listen(window.show_requested.emit)
    api.request_quit = window.quit_requested.emit  # обновление закрывает программу через поток UI
    control.start_for(api)  # канал для `chimera ...` (modules/control.py); quit/restart идут тем же выходом

    def _on_closing():
        if listener:
            listener.close()
        # невзятые вызовы отменяем и не ждём взятые: иначе висящий на выходе
        # запрос (проверка обновлений, скачивание ядра) держал бы процесс
        bridge.pool.shutdown(wait=False, cancel_futures=True)
        api.shutdown()

    app.aboutToQuit.connect(_on_closing)
    # с Windows (--tray) — только значок; без трея окно показываем всегда, иначе
    # программу было бы не достать
    if not (tray and "--tray" in sys.argv):
        window.show()
    sys.exit(app.exec())
