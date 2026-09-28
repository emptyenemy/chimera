"""Обновление программы для окна: состояние, фоновая проверка, установка по кнопке.

Сами проверка, скачивание и apply.cmd — modules/selfupdate.py; тут — то, что
между ними и API: что показывать во фронте (snapshot), когда проверять
(раз в 6 часов, если включено в настройках) и порядок установки: сначала
всё, что может упасть (скачать, сверить, распаковать), и только потом гасить
модули и выходить — ошибка на середине оставляет программу работать как была.
"""

import os
import threading
import time

from modules import appconfig, paths, selfupdate, service
from modules.version import VERSION

UPDATE_DIR = selfupdate.UPDATE_DIR
FIRST_CHECK_DELAY = 15        # с после старта: не мешать поднятию модулей
CHECK_INTERVAL = 6 * 3600
SERVICE_STOP_TIMEOUT = 15     # с на остановку службы перед заменой файлов


class Updater:
    def __init__(self, on_change=lambda: None):
        self._on_change = on_change
        self._lock = threading.Lock()
        self._asset = None
        self._state = {
            "current": VERSION, "latest": None, "update": False, "installable": False,
            "notes": "", "url": None, "error": None, "checked_at": None,
            "checking": False, "stage": "idle", "progress": 0.0,
            "frozen": paths.IS_FROZEN,
        }

    # --- состояние ---------------------------------------------------------------

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)
        self._on_change()

    def snapshot(self) -> dict:
        cfg = appconfig.load()
        with self._lock:
            return {**self._state, "channel": cfg.get("update_channel", "stable"),
                    "auto": bool(cfg.get("update_check", True))}

    # --- проверка ----------------------------------------------------------------

    def check(self) -> dict:
        self._set(checking=True)
        try:
            channel = appconfig.load().get("update_channel", "stable")
            res = selfupdate.check(channel=channel, current=VERSION)
        finally:
            self._set(checking=False)
        self._asset = res.pop("asset", None)
        self._set(**res, checked_at=time.time(),
                  stage="idle" if self._state["stage"] == "error" else self._state["stage"])
        return self.snapshot()

    def start_background(self, stop: threading.Event) -> None:
        """Проверка при запуске (через FIRST_CHECK_DELAY) и раз в CHECK_INTERVAL, если включена."""
        def loop():
            delay = FIRST_CHECK_DELAY
            while not stop.wait(delay):
                delay = CHECK_INTERVAL
                if appconfig.load().get("update_check", True):
                    try:
                        self.check()
                    except Exception:
                        pass  # сеть и прочее уже в error; падать фоновому потоку незачем
        threading.Thread(target=loop, daemon=True, name="selfupdate-check").start()

    # --- установка ---------------------------------------------------------------

    def install(self, shutdown, request_quit) -> dict:
        """Ставит найденную версию: скачать → распаковать → погасить модули → apply.cmd → выход.

        shutdown() гасит модули программы, request_quit() закрывает её (поток UI
        сам решает как); после request_quit процесс должен завершиться — apply.cmd
        ждёт именно его выхода.
        """
        if not paths.IS_FROZEN:
            raise RuntimeError("Запуск из исходников — обновляется через git, не из программы")
        if not (self._state["installable"] and self._asset):
            raise RuntimeError("Нечего ставить — сначала проверь обновления")
        asset = dict(self._asset)
        restart_service = service.is_running()
        try:
            self._set(stage="downloading", progress=0.0, error=None)
            zip_path = selfupdate.download(
                asset, UPDATE_DIR / "download",
                progress=lambda done, total: self._set(progress=(done / total) if total else 0.0))
            staged = selfupdate.stage(zip_path, UPDATE_DIR / "staged")
            # копия текущей версии для отката — тоже до выхода: не вышло, работаем дальше как были
            script = selfupdate.write_script(
                paths.APP_DIR, staged, os.getpid(), restart_service=restart_service, relaunch=True,
                script=UPDATE_DIR / "apply.cmd", log=selfupdate.LOG_PATH, rollback=UPDATE_DIR / "rollback")
        except Exception as e:
            self._set(stage="error", error=str(e))
            raise

        self._set(stage="installing", progress=1.0)
        if restart_service:
            # служба держит тот же exe — пока она жива, файлы не заменить
            service.send_stop()
            deadline = time.time() + SERVICE_STOP_TIMEOUT
            while service.is_running() and time.time() < deadline:
                time.sleep(0.3)
        shutdown()
        selfupdate.launch(script)
        request_quit()
        return self.snapshot()
