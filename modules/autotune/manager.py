"""Сессия автонастройки у владельца модулей: поток подбора, отмена, откат, запись на диск.

Перед подбором ops.capture() сохраняет точное состояние модулей; запись лежит в
data/autotune.json, пока сессия не закрыта. Закрылась программа посреди подбора —
при следующем запуске recover() возвращает исходное состояние. После подбора
результат уже применён; «Вернуть как было» (revert) доступно, пока его не оставили (keep)
или не начали новую автонастройку.

Изменения из потока подбора идут под общей блокировкой изменений и после проверки
отмены: «Выключить всё» не столкнётся с подбором и не будет перебито следующим вариантом.
"""

import json
import re
import secrets
import threading
import time
from copy import deepcopy

from modules import control
from modules.autotune import memory as memory_mod
from modules.autotune import provider as provider_mod
from modules.autotune import report as report_mod
from modules.autotune.engine import MODES, Cancelled, Engine
from modules.errors import ChimeraError
from modules.fileutil import atomic_write_text

ID_RE = re.compile(r"[a-f0-9]{16}")
RUNNING = "running"
LOG_LIMIT = 60
# Операции, которые меняют систему: в потоке подбора — только под блокировкой и без отмены.
MUTATIONS = ("prepare_strategy", "apply_strategy", "commit_strategy", "restore_strategy", "assign_hosts",
             "apply_dns", "keep_dns", "revert_dns", "apply_proxy", "commit_proxy", "restore_proxy")
PUBLIC = ("id", "phase", "mode", "trigger", "services", "stage", "current", "log", "report", "error", "reason",
          "started", "finished", "cancelling")
# кто начал подбор: пользователь или самолечение в фоне (modules/autotune/watch.py)
TRIGGERS = ("user", "watch")


class _GuardedOps:
    def __init__(self, ops, lock, cancel):
        self._ops, self._lock, self._cancel = ops, lock, cancel

    def __getattr__(self, name):
        attr = getattr(self._ops, name)
        if name not in MUTATIONS:
            return attr

        def guarded(*args, **kwargs):
            with self._lock:
                if self._cancel.is_set():
                    raise Cancelled()
                return attr(*args, **kwargs)
        return guarded


class AutotuneManager:
    def __init__(self, ops, path, lock, *, memory_path=None, worker=None, changed=None, load_pending=True,
                 engine=Engine, now=time.time):
        self.ops, self.path, self.lock = ops, path, lock
        self.memory_path = memory_path or memory_mod.PATH
        self.worker = worker or self._worker
        self.changed = changed or (lambda: None)
        self.engine = engine
        self.now = now
        self._records = threading.RLock()   # быстрая: состояние читает хаб каждую секунду
        self.active = self.last = None
        self._cancel = threading.Event()
        if load_pending:
            self._load()

    @staticmethod
    def _worker(fn):
        threading.Thread(target=fn, daemon=True, name="autotune").start()

    # --- запись на диск ------------------------------------------------------------------

    def _load(self):
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (value.get("schema") != 1 or not ID_RE.fullmatch(str(value.get("id")))
                    or not isinstance(value.get("before"), dict) or value.get("phase") not in (RUNNING, "done")):
                raise ValueError
        except (OSError, ValueError, TypeError, AttributeError):
            # Повреждённая запись не даёт начать подбор поверх неизвестного состояния.
            self.active = {"id": None, "phase": "invalid", "error": "err.autotune.invalid_record"}
            return
        if value["phase"] == RUNNING:
            value["phase"] = "interrupted"
        self.active = value

    def _save(self):
        # в записи исходное состояние со ссылкой прокси: права закрываются до подмены файла
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(self.active, ensure_ascii=False), prepare=control._restrict_permissions)

    def _close(self, phase, reason=None):
        """Сессия закончилась: исходное состояние больше не нужно."""
        rec = self.active
        rec["phase"], rec["reason"] = phase, reason
        rec.pop("before", None)
        self.path.unlink(missing_ok=True)
        self.last, self.active = rec, None

    # --- состояние -----------------------------------------------------------------------

    def _public(self, rec):
        if rec is None:
            return None
        return {k: deepcopy(rec.get(k)) for k in PUBLIC}

    def state(self):
        with self._records:
            return {"active": self._public(self.active), "last": self._public(self.last)}

    def busy(self):
        return self.active is not None and self.active["phase"] == RUNNING

    def blocks_changes(self):
        """Пока идёт подбор или неизвестно, чем кончилась прошлая сессия, менять настройки нельзя."""
        return self.active is not None and self.active["phase"] in (RUNNING, "interrupted", "invalid", "rollback_failed")

    def catalog(self):
        return self.ops.services()

    def _services(self, services):
        names = [s["name"] for s in self.ops.services()]
        if not services:
            return names
        if isinstance(services, str) or not isinstance(services, (list, tuple)):
            raise ChimeraError("err.autotune.arguments")
        for name in services:
            if name not in names:
                raise ChimeraError("err.autotune.unknown_service", name=str(name))
        return list(dict.fromkeys(services))

    def diagnose(self, services=None):
        return self.engine(self.ops).diagnose(self._services(services))

    # --- сессия --------------------------------------------------------------------------

    def start(self, services=None, mode="fast", trigger="user"):
        if mode not in MODES or trigger not in TRIGGERS:
            raise ChimeraError("err.autotune.arguments")
        services = self._services(services)
        with self.lock, self._records:
            if self.blocks_changes():
                raise ChimeraError("err.autotune.busy")
            if self.active is not None:     # прошлый результат молча оставляем
                self._close("kept")
            self.ops.require_admin()
            before = self.ops.capture()
            self.ops.snapshot()
            record = {"schema": 1, "id": secrets.token_hex(8), "phase": RUNNING, "mode": mode, "trigger": trigger, "services": services,
                      "before": before, "stage": "diagnose", "current": None, "log": [], "report": None,
                      "started": self.now()}
            self.active = record
            try:
                self._save()
            except OSError:
                self.active = None
                raise ChimeraError("err.autotune.save") from None
            self._cancel = threading.Event()
            cancel = self._cancel
        self.worker(lambda: self._run(record["id"], cancel))
        self.changed()
        return self.state()

    def _progress(self, record_id, event):
        with self._records:
            rec = self.active
            if rec is None or rec["id"] != record_id:
                return
            if event["type"] == "phase":
                rec["stage"], rec["current"] = event["phase"], None
            elif event["type"] == "candidate":
                rec["current"] = {k: event[k] for k in ("step", "candidate", "index", "total")}
            else:
                rec["log"] = (rec["log"] + [event])[-LOG_LIMIT:]
        self.changed()

    def _network_key(self):
        try:
            return self.ops.network_key()
        except Exception:
            return None

    def _provider(self, key):
        """Провайдер сети: из памяти, а если не узнавали — у RIPEstat (сеть, вне блокировок)."""
        found = memory_mod.provider(key, self.memory_path)
        if found is None:
            try:
                found = self.ops.lookup_provider()
            except Exception:
                found = None
            memory_mod.remember_provider(key, found, self.memory_path)
        return found

    def _hints(self, key):
        """Подсказки карты провайдеров; пока карта пуста, RIPEstat не спрашиваем вовсе."""
        try:
            providers = self.ops.provider_map()
        except Exception:
            providers = {}
        if not providers:
            return None, {}
        found = self._provider(key)
        return found, provider_mod.hints(providers, found)

    def _run(self, record_id, cancel):
        key = self._network_key()
        provider, hints = self._hints(key)
        with self._records:
            rec = self.active
            if rec is None or rec["id"] != record_id:
                return
            services, mode = rec["services"], rec["mode"]
            rec["provider"] = provider
        engine = self.engine(_GuardedOps(self.ops, self.lock, cancel), mode=mode,
                             memory=memory_mod.load(key, self.memory_path), hints=hints,
                             progress=lambda event: self._progress(record_id, event), cancel=cancel)
        try:
            report = engine.run(services)
        except Cancelled:
            self._rollback(record_id, "cancelled")
            return
        except Exception as e:
            self._rollback(record_id, "failed", error=str(e) or type(e).__name__)
            return
        memory_mod.remember(key, report["fixes"], self.memory_path)
        with self.lock, self._records:
            rec = self.active
            if rec is None or rec["id"] != record_id:
                return
            rec.update(phase="done", stage=None, current=None, report=report, finished=self.now(), cancelling=None)
            try:
                self._save()
            except OSError:
                pass  # результат уже применён; без записи «Вернуть как было» не переживёт перезапуск
        self.changed()

    def _rollback(self, record_id, phase, error=None):
        with self.lock, self._records:
            rec = self.active
            if rec is None or rec["id"] != record_id:
                return   # сессию уже закрыло «Выключить всё»
            self._restore(rec, phase, error)
        self.changed()

    def _restore(self, rec, phase, error=None):
        try:
            self.ops.restore(deepcopy(rec["before"]))
        except Exception:
            rec.update(phase="rollback_failed", error="err.autotune.rollback", stage=None, current=None)
            try:
                self._save()
            except OSError:
                pass
            return
        rec.update(error=error, stage=None, current=None, finished=self.now(), cancelling=None)
        self._close(phase)

    def cancel(self):
        with self._records:
            if not self.busy():
                raise ChimeraError("err.autotune.not_running")
            self.active["cancelling"] = True
            self._cancel.set()
        self.changed()
        return self.state()

    def revert(self):
        """Вернуть состояние до автонастройки: после подбора, после аварии или повтор отката."""
        with self.lock, self._records:
            rec = self.active
            if rec is None or rec["phase"] not in ("done", "interrupted", "rollback_failed"):
                raise ChimeraError("err.autotune.nothing_to_revert")
            self._restore(rec, "reverted")
            failed = self.active is not None
        self.changed()
        if failed:
            raise ChimeraError("err.autotune.rollback")
        return self.state()

    def share(self):
        """Отчёт о последнем подборе для issue на GitHub. Ничего не отправляет: только текст и ссылка."""
        with self._records:
            rec = self.active if self.active is not None and self.active.get("report") else self.last
            if rec is None or not rec.get("report"):
                raise ChimeraError("err.autotune.nothing_to_share")
            rec = deepcopy({k: rec.get(k) for k in ("mode", "report", "provider")})
        if rec["provider"] is None:
            rec["provider"] = self._provider(self._network_key())
        return report_mod.build(rec, self.ops.about())

    def keep(self):
        with self._records:
            if self.active is None or self.active["phase"] != "done":
                raise ChimeraError("err.autotune.nothing_to_keep")
            self._close("kept")
        self.changed()
        return self.state()

    def recover(self):
        """У владельца модулей при запуске и выходе: недоделанный подбор откатывается."""
        with self.lock, self._records:
            rec = self.active
            if rec is not None and rec["phase"] == "interrupted":
                self._restore(rec, "interrupted")
            elif rec is not None and rec["phase"] == RUNNING:
                self._cancel.set()
                self._restore(rec, "interrupted")
        self.changed()

    def abandon(self):
        """«Выключить всё» сильнее подбора: модули остаются выключенными, отката нет."""
        with self._records:
            if self.active is None:
                return
            self._cancel.set()
            self.active.update(stage=None, current=None, finished=self.now())
            self._close("cancelled", "panic")
        self.changed()
