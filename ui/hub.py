"""Хаб состояния: фоновые опросы модулей и push изменений во фронт.

Раньше фронт сам дёргал *_state по таймеру, и каждый клик вставал в очередь за
опросами (winws_state — это tasklist + git, dns_state — PowerShell на секунды).
Теперь фронт вообще не ждёт бэкенд: состояние лежит у него в сторе, а сюда он
только шлёт команды. Хаб опрашивает каждый источник в своём потоке (медленный
dns не держит быстрые) и пушит `hub({key, data})` только когда данные реально
поменялись — окно не перерисовывает одно и то же каждые пару секунд.

Источники с `lazy=True` опрашиваются, только пока их кто-то смотрит (открыта
вкладка): фронт сообщает это через `hub_watch`. После любой команды модуля
(winws_start, proxy_set_mode, …) его источник перечитывается сразу — `poke()`
из Api.dispatch, так что UI получает факт через доли секунды, а не на след. тике.
"""

import json
import threading
import time


class _Source:
    def __init__(self, key, fn, interval, lazy=False):
        self.key = key
        self.fn = fn
        self.interval = interval
        self.lazy = lazy
        self.watchers = 0
        self.force = False  # после команды пушим, даже если данные не поменялись
        self.wake = threading.Event()
        self.last_json = None
        self.data = None
        self.error = None
        self.updated = 0.0


class StateHub:
    def __init__(self, push, sources):
        """push(key, data) — доставка во фронт; sources — [(key, fn, interval, lazy)]."""
        self._push = push
        self._sources = {k: _Source(k, fn, iv, lazy) for k, fn, iv, lazy in sources}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads = []

    def start(self):
        for src in self._sources.values():
            t = threading.Thread(target=self._loop, args=(src,), daemon=True,
                                 name=f"hub-{src.key}")
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        for src in self._sources.values():
            src.wake.set()

    # --- API для фронта -----------------------------------------------------

    def snapshot(self) -> dict:
        """Всё, что уже известно, — мгновенно, без опросов (первый рендер окна)."""
        with self._lock:
            return {k: s.data for k, s in self._sources.items() if s.data is not None}

    def watch(self, keys, on=True):
        """Вкладка открылась/закрылась — включить/выключить ленивые источники."""
        for k in keys or []:
            src = self._sources.get(k)
            if not src:
                continue
            with self._lock:
                src.watchers = max(0, src.watchers + (1 if on else -1))
            if on:
                src.wake.set()  # открыли вкладку — свежие данные сразу, не через интервал

    def poke(self, *keys):
        """Перечитать источник вне очереди (после команды, которая его меняет)."""
        for k in keys:
            src = self._sources.get(k)
            if src:
                # фронт мог отбросить пуш, пока ждал ответ команды (оптимистичная
                # правка) — поэтому следующий снимок уходит в любом случае
                with self._lock:
                    src.force = True
                src.wake.set()

    # --- цикл опроса --------------------------------------------------------

    def _active(self, src) -> bool:
        return not src.lazy or src.watchers > 0

    def _loop(self, src):
        while not self._stop.is_set():
            src.wake.clear()
            if self._active(src):
                self._poll(src)
                src.wake.wait(src.interval)
            else:
                src.wake.wait()  # спим, пока вкладку не откроют

    def _poll(self, src):
        with self._lock:
            force = src.force
            src.force = False
        try:
            res = src.fn()
        except Exception as e:  # модуль упал — фронт увидит ошибку, хаб живёт дальше
            res = {"ok": False, "error": str(e)}
        data = res.get("data") if res.get("ok") else None
        err = None if res.get("ok") else res.get("error")
        payload = {"key": src.key, "data": data, "error": err, "ts": time.time()}
        try:
            as_json = json.dumps([data, err], sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            as_json = None
        with self._lock:
            if self._stop.is_set() or src.force:
                return  # команда во время опроса: дождёмся нового снимка
            changed = as_json is None or as_json != src.last_json or force
            src.last_json = as_json
            if data is not None:
                src.data = data
            src.error = err
            src.updated = payload["ts"]
        if changed:
            try:
                self._push(src.key, payload)
            except Exception:
                with self._lock:
                    src.force = True  # следующий опрос повторит недоставленный снимок
