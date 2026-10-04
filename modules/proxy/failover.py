"""Переключение сервера подписки при отказе.

Раз в INTERVAL проверяется выбранный сервер: TCP-подключение к его порту. Не ответил
STREAK проверок подряд — прокси переходит на самый быстрый из отвечающих серверов
подписки. Работает, только пока запущен свой прокси и в подписке больше одного сервера.
QUIC-серверы (Hysteria, TUIC, WireGuard) по TCP не проверить — их не трогаем.

Тестируется без потоков и сети: run_once() делает один проход синхронно.
"""

import threading
import time

from modules import applog
from modules.proxy import subscription

INTERVAL = 5 * 60
STREAK = 2


class ProxyFailover:
    def __init__(self, proxy, *, now=time.time):
        self.proxy, self.now = proxy, now
        self.fails = 0
        self.watched = None   # ссылка, за которой следим: сменили сервер — счёт заново

    def run_once(self):
        proxy = self.proxy
        servers = list(proxy.config.get("servers") or [])
        current = proxy.config.get("link") or ""
        if len(servers) < 2 or current not in servers or not proxy._ours_alive:
            self.fails, self.watched = 0, None
            return None
        if current != self.watched:
            self.fails, self.watched = 0, current
        try:
            if subscription._endpoint(current)[2] in subscription.UDP_TYPES:
                return None
        except (ValueError, TypeError):
            return None
        if subscription.ping(current) is not None:
            self.fails = 0
            return {"ok": True}
        self.fails += 1
        if self.fails < STREAK:
            return {"ok": False, "fails": self.fails}
        pings = subscription.ping_all(servers)
        if pings[servers.index(current)] is not None:
            self.fails = 0   # при общем замере ответил: ожил, выбор пользователя не трогаем
            return {"ok": True}
        alive = [(ms, i) for i, ms in enumerate(pings) if ms is not None]
        if not alive:
            return {"ok": False, "fails": self.fails, "switched": False}
        best = min(alive)[1]
        old = subscription.summary(current)["label"]
        proxy.select_server(best)
        new = subscription.summary(servers[best])["label"]
        proxy.last_switch = {"from": old, "to": new, "at": self.now()}
        applog.write(f"Прокси: сервер «{old}» перестал отвечать, переключено на «{new}»")
        self.fails, self.watched = 0, servers[best]
        return {"ok": False, "switched": True, "to": best}

    def start_background(self, stop: threading.Event, interval=INTERVAL):
        def loop():
            while not stop.wait(interval):
                try:
                    self.run_once()
                except Exception as e:   # фоновый поток не должен умирать из-за одного прохода
                    applog.write(f"Прокси: проверка сервера не удалась: {e}")

        threading.Thread(target=loop, daemon=True, name="proxy-failover").start()
