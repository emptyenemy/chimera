"""Единый фоновый поток вкладки Hosts: автообновление IP у dns-привязок,
TCP+TLS-чекер применённых записей и автопереключение деградировавшей привязки
на следующий живой dns-провайдер.

Один поток на все три задачи (не три отдельных потока) — они дешёвые и не
крутятся часто (часы/минуты), плюс общее состояние (health, streak) удобнее
без блокировок между потоками. HostsManager создаёт один экземпляр и
управляет им через start_background()/stop_background(); Api стартует его в
__init__ и гасит в shutdown().

Тестируется без sleep и без сети: run_once(now=...) выполняет один тик
синхронно, резолвер/чекер/проба провайдера — инжектируемые функции.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .. import blockcheck
from ..domains import split_lists

CHECK_MAX_WORKERS = 32  # применённых записей может быть много (десятки списков) — гоним параллельно

DEGRADE_RATIO = 0.5   # ниже этой доли живых записей привязка считается деградировавшей
DEGRADE_STREAK = 2    # столько тиков подряд деградации нужно, чтобы переключиться

STARTUP_CHECK_DELAY = 60  # сек от запуска до первой фоновой проверки записей

DEFAULT_OPTIONS = {
    "refresh_enabled": True,
    "refresh_interval": 6 * 3600,   # автообновление IP dns-привязок, сек
    "check_enabled": True,
    "check_interval": 15 * 60,      # чекер применённых записей, сек
    "autoswitch_enabled": False,
    "provider_order": [],           # порядок dns-провайдеров для автопереключения
}


def _check_via_blockcheck(host: str) -> bool:
    try:
        return blockcheck.check(host).get("status") == "ok"
    except Exception:
        return False


class HostsBackground:
    def __init__(self, manager, resolve_fn=None, check_fn=None, probe_fn=None,
                 now=time.monotonic, tick_interval: float = 30.0):
        self.manager = manager
        self.resolve_fn = resolve_fn  # None -> берём modules.hosts.resolver.resolve_domains лениво
        self.check_fn = check_fn or _check_via_blockcheck
        self.probe_fn = probe_fn or self._default_probe
        self.now = now
        self.tick_interval = tick_interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_refresh = 0.0
        self._last_check = 0.0
        self._degraded_streak: dict[str, int] = {}

    # --- запуск/остановка потока ---------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        # На старте hosts уже применён прошлым запуском — пересолв ждёт полный
        # интервал, а первая проверка идёт через минуту. Иначе окно, закрытое в
        # первые секунды, ждало бы выхода, пока пулы добегут сетевые таймауты.
        now = self.now()
        opts = self.manager.background_options()
        self._last_refresh = now
        self._last_check = now - opts.get("check_interval", DEFAULT_OPTIONS["check_interval"]) + STARTUP_CHECK_DELAY
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                pass  # фон не должен ронять программу; последняя ошибка видна по health/логу
            self._stop.wait(self.tick_interval)

    # --- один тик (вызывается и потоком, и тестами напрямую) -----------------

    def run_once(self, now: float | None = None) -> None:
        now = self.now() if now is None else now
        opts = self.manager.background_options()

        if opts.get("refresh_enabled", True) and \
                now - self._last_refresh >= opts.get("refresh_interval", DEFAULT_OPTIONS["refresh_interval"]):
            self._refresh()
            self._last_refresh = now

        if opts.get("check_enabled", True) and \
                now - self._last_check >= opts.get("check_interval", DEFAULT_OPTIONS["check_interval"]):
            self._do_check(opts)
            self._last_check = now

    # --- автообновление IP у dns-привязок -------------------------------------

    def _resolve(self, domains_, doh, servers):
        if self.resolve_fn is not None:
            return self.resolve_fn(domains_, doh, servers)
        from .resolver import resolve_domains  # локальный импорт — тесты подменяют resolve_fn напрямую
        return resolve_domains(domains_, doh, servers)

    def _refresh(self) -> None:
        st = self.manager._load_state()
        if not st.get("enabled", True):
            return
        plan = {pid: lists for pid, lists in st.get("assignments", {}).items() if lists}
        before = {(e["host"], e.get("provider")): e["ip"] for e in st.get("entries", [])}

        changed = False
        for pid, lists in plan.items():
            try:
                provider = self.manager.get_provider(pid)
            except KeyError:
                continue
            if provider.get("type") == "static":
                continue  # static ничего не резолвит — обновляется вместе с сабмодулем сам
            domains_, _ = split_lists(lists)
            try:
                entries = self._resolve(domains_, provider.get("doh"), provider.get("servers"))
            except Exception:
                continue
            for e in entries:
                if before.get((e["host"], pid)) != e["ip"]:
                    changed = True

        if changed:
            try:
                self.manager._sync()
            except Exception:
                pass  # нет прав/сеть пропала — попробуем на следующем тике

    # --- TCP+TLS чекер применённых записей ------------------------------------

    def _check_one(self, host: str) -> bool:
        try:
            return bool(self.check_fn(host))
        except Exception:
            return False

    def _do_check(self, opts: dict) -> None:
        st = self.manager._load_state()
        entries = st.get("entries", [])
        if not entries:
            return

        # применённых записей бывают десятки-сотни (несколько списков разом) — гоним
        # TCP+TLS параллельно, иначе один тик чекера растянется на минуты (по
        # OVERALL_TIMEOUT блокчекера на каждую мёртвую запись последовательно).
        with ThreadPoolExecutor(max_workers=min(CHECK_MAX_WORKERS, len(entries))) as pool:
            alive_flags = list(pool.map(lambda e: self._check_one(e["host"]), entries))

        by_provider: dict[str, dict] = {}
        for e, alive in zip(entries, alive_flags, strict=True):
            h = by_provider.setdefault(e.get("provider"), {"alive": 0, "total": 0})
            h["total"] += 1
            h["alive"] += int(alive)

        provider_health = {
            pid: {**h, "ratio": (h["alive"] / h["total"]) if h["total"] else 0.0}
            for pid, h in by_provider.items()
        }

        total = sum(h["total"] for h in provider_health.values())
        alive_total = sum(h["alive"] for h in provider_health.values())
        health = {
            "checked_at": time.time(),  # для показа «N мин назад»; расписание — на self.now (monotonic)
            "alive": alive_total,
            "total": total,
            "ratio": (alive_total / total) if total else None,
            "providers": provider_health,
        }

        st = self.manager._load_state()  # перечитать: assignments мог поменять _refresh() рядом
        st["health"] = health
        self.manager._save_state(st)

        if opts.get("autoswitch_enabled"):
            self._maybe_autoswitch(opts, provider_health)

    # --- автопереключение деградировавшей привязки ----------------------------

    def _default_probe(self, provider_id: str) -> bool:
        try:
            return bool(self.manager.ping_one(provider_id).get("ok"))
        except Exception:
            return False

    def _next_alive_provider(self, current: str, order: list[str]) -> str | None:
        if current in order:
            i = order.index(current)
            candidates = order[i + 1:] + order[:i]
        else:
            candidates = [p for p in order if p != current]
        for pid in candidates:
            if self.probe_fn(pid):
                return pid
        return None

    def _maybe_autoswitch(self, opts: dict, provider_health: dict) -> None:
        order = opts.get("provider_order") or []
        for pid, health in provider_health.items():
            try:
                provider = self.manager.get_provider(pid)
            except KeyError:
                continue
            if provider.get("type") == "static" or health["total"] == 0:
                continue

            if health["ratio"] < DEGRADE_RATIO:
                self._degraded_streak[pid] = self._degraded_streak.get(pid, 0) + 1
            else:
                self._degraded_streak[pid] = 0
                continue

            if self._degraded_streak.get(pid, 0) < DEGRADE_STREAK:
                continue

            st = self.manager._load_state()
            assignments = st.get("assignments", {})
            lists = assignments.get(pid)
            if not lists:
                self._degraded_streak[pid] = 0
                continue

            nxt = self._next_alive_provider(pid, order)
            if not nxt or nxt == pid:
                continue  # переключить некуда — остаёмся на текущем, ждём восстановления

            assignments[nxt] = lists
            del assignments[pid]
            st["assignments"] = assignments
            event = {
                "from": pid, "to": nxt, "when": time.time(),
                "reason": f"деградация: {health['alive']}/{health['total']} живы",
            }
            log = st.get("switch_log", []) + [event]
            st["switch_log"] = log[-20:]  # не растим файл бесконечно
            st["last_switch"] = event
            self.manager._save_state(st)
            self._log_switch(event)
            self._degraded_streak[pid] = 0

            try:
                self.manager._sync()
            except Exception:
                pass
            break  # одно переключение за тик — остальные (если есть) разберём на следующем

    def _log_switch(self, event: dict) -> None:
        try:
            from .. import paths
            path = paths.log_path("hosts.log")
            line = (f"[автопереключение] {event['from']} -> {event['to']}: "
                    f"{event['reason']}\n")
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass  # лог — не критично, само переключение уже применено и записано в state
