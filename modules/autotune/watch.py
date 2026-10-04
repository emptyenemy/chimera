"""Самолечение в фоне, по желанию: следит за сервисами, которые автонастройка уже чинила
в этой сети, и чинит их снова, если они перестали открываться.

Раз в INTERVAL — лёгкая проверка без изменений (тот же диагноз, что «Проверить»). Сервис,
который не открылся STREAK проверок подряд при живом интернете, получает быстрый подбор
только для себя. Одна проверка — не повод: сайт мог моргнуть. Пока идёт подбор, проба или
незакрытая сессия, наблюдатель ничего не делает. По умолчанию выключен (config.json →
autotune_watch); без прав администратора подбор не начнётся — это пишется в журнал.

Тестируется без потоков и сети: run_once() делает один проход синхронно.
"""

import threading

from modules import applog
from modules.autotune import memory as memory_mod
from modules.errors import ChimeraError

INTERVAL = 15 * 60
STARTUP_DELAY = 120   # первая проверка — когда автозапуски уже поднялись
STREAK = 2


class AutotuneWatch:
    def __init__(self, manager, *, enabled, can_run=lambda: True, memory_path=None):
        self.manager = manager
        self.enabled, self.can_run = enabled, can_run
        self.memory_path = memory_path or memory_mod.PATH
        self.streak = {}
        self.last = None   # итог последнего прохода: для состояния и журнала

    def watched(self):
        """Сервисы, которые автонастройка уже чинила в текущей сети."""
        try:
            key = self.manager.ops.network_key()
        except Exception:
            return []
        names = {s["name"] for s in self.manager.catalog()}
        return [name for name in memory_mod.load(key, self.memory_path) if name in names]

    def run_once(self):
        if not self.enabled() or not self.can_run() or self.manager.blocks_changes():
            return None
        services = self.watched()
        if not services:
            self.streak.clear()
            return None
        result = self.manager.diagnose(services)
        if result.get("offline"):
            self.streak.clear()   # без интернета чинить нечего, счёт начнётся заново
            self.last = {"checked": services, "offline": True}
            return self.last
        for row in result["services"]:
            if row.get("ok") is False:
                self.streak[row["name"]] = self.streak.get(row["name"], 0) + 1
            else:
                self.streak.pop(row["name"], None)
        due = [name for name, count in self.streak.items() if count >= STREAK]
        self.last = {"checked": services, "due": due}
        if due:
            try:
                self.manager.start(due, "fast", trigger="watch")
                applog.write(f"Самолечение: сервисы перестали открываться, начат подбор: {', '.join(due)}")
                for name in due:
                    self.streak.pop(name, None)
            except ChimeraError as e:
                self.last["error"] = e.code
                applog.write(f"Самолечение не начало подбор для {', '.join(due)}: {e}")
        return self.last

    def start_background(self, stop: threading.Event, interval=INTERVAL, startup_delay=STARTUP_DELAY):
        def loop():
            if stop.wait(startup_delay):
                return
            while not stop.is_set():
                try:
                    self.run_once()
                except Exception as e:   # фоновый поток не должен умирать из-за одного прохода
                    applog.write(f"Самолечение: проход не удался: {e}")
                if stop.wait(interval):
                    return

        threading.Thread(target=loop, daemon=True, name="autotune-watch").start()
