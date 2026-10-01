"""Одна проба настроек с проверкой доступности и откатом у владельца модулей."""

import json
import math
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from modules import control
from modules.errors import ChimeraError

KINDS = ("strategy", "hosts", "tun")
DEFAULT_DOMAINS = ("example.com", "cloudflare.com")
ID_RE = re.compile(r"[a-f0-9]{16}")
DOMAIN_RE = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def _schedule(seconds, callback):
    timer = threading.Timer(seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


class TrialManager:
    def __init__(self, ops, path, lock, *, now=time.monotonic, schedule=_schedule, worker=None, changed=None, load_pending=True):
        self.ops, self.path, self.lock = ops, path, lock
        self.now, self.schedule = now, schedule
        self.worker = worker or self._worker
        self.changed = changed or (lambda: None)
        self.active = self.last = self.timer = None
        self.deadline = 0.0
        self._cancelled_id = None
        if load_pending:
            self._load()

    @staticmethod
    def _worker(fn):
        threading.Thread(target=fn, daemon=True, name="trial-checks").start()

    def _load(self):
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (type(value.get("schema")) is not int or value.get("schema") != 1 or not isinstance(value.get("id"), str)
                    or not ID_RE.fullmatch(value["id"]) or value.get("kind") not in KINDS
                    or not isinstance(value.get("before"), dict) or not isinstance(value.get("target"), str)):
                raise ValueError
            if value.get("phase") == "cancelled" or value["id"] == self._cancelled_id:
                return
            self.active = {**value, "phase": "interrupted", "checks": [], "checks_done": False}
        except (OSError, ValueError, TypeError, AttributeError):
            # Повреждённый файл не разрешает пробу поверх неизвестного состояния.
            self.active = {"id": None, "kind": None, "target": None, "phase": "invalid", "checks": [], "checks_done": False,
                           "error": "err.trial.invalid_record"}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(self.active, ensure_ascii=False), encoding="utf-8")
            control._restrict_permissions(temp)
            temp.replace(self.path)
        finally:
            temp.unlink(missing_ok=True)

    def _public(self, record):
        if record is None:
            return None
        data = {k: deepcopy(record.get(k)) for k in ("id", "kind", "target", "phase", "checks", "checks_done", "reason", "error")}
        data["seconds_left"] = max(0, math.ceil(self.deadline - self.now())) if record is self.active and record["phase"] == "pending" else 0
        return data

    def state(self):
        with self.lock:
            if self.active is None and self.path.exists():
                self._load()
            return {"active": self._public(self.active), "last": self._public(self.last)}

    def guard(self):
        if self.active is not None:
            raise ChimeraError("err.trial.busy")

    def start(self, kind, target, seconds=60, domains=None):
        if (kind not in KINDS or not isinstance(target, str) or isinstance(seconds, bool)
                or not isinstance(seconds, int) or not 15 <= seconds <= 300):
            raise ChimeraError("err.trial.arguments")
        domains = list(DEFAULT_DOMAINS) if domains is None else domains
        if not isinstance(domains, (list, tuple)) or not 1 <= len(domains) <= 6:
            raise ChimeraError("err.trial.domains")
        names = []
        for domain in domains:
            if not isinstance(domain, str) or not DOMAIN_RE.fullmatch(domain.lower()):
                raise ChimeraError("err.trial.domains")
            if domain.lower() not in names:
                names.append(domain.lower())
        with self.lock:
            if self.active is None and self.path.exists():
                self._load()
            self.guard()
            before = self.ops.capture(kind, target)
            record = {"schema": 1, "id": secrets.token_hex(8), "kind": kind, "target": target, "before": before,
                      "phase": "applying", "checks": [], "checks_done": False}
            self.active = record
            try:
                self._save()
            except OSError:
                self.active = None
                raise ChimeraError("err.trial.save") from None
            try:
                self.ops.apply(kind, target)
                record["phase"] = "pending"
                self.deadline = self.now() + seconds
                self._save()
                trial_id = record["id"]
                self.timer = self.schedule(seconds, lambda: self._expire(trial_id))
                self.worker(lambda: self._check(trial_id, names))
            except Exception:
                self._revert("apply_failed")
                raise ChimeraError("err.trial.apply") from None
            self.changed()
            return self.state()

    def _require(self, trial_id):
        if self.active is None or self.active.get("id") != trial_id or trial_id is None:
            raise ChimeraError("err.trial.not_found")
        return self.active

    def confirm(self, trial_id):
        with self.lock:
            record = self._require(trial_id)
            if record["phase"] != "pending" or self.now() >= self.deadline:
                if record["phase"] == "pending":
                    self._revert("timeout")
                raise ChimeraError("err.trial.expired")
            if not record["checks_done"]:
                raise ChimeraError("err.trial.checking")
            self.path.unlink(missing_ok=True)
            self._finish("confirmed")
            return self.state()

    def revert(self, trial_id):
        with self.lock:
            self._require(trial_id)
            self._revert("cancelled")
            return self.state()

    def recover(self):
        with self.lock:
            if self.active is not None and self.active["phase"] != "invalid":
                self._revert("interrupted")

    def abandon(self):
        """Аварийное выключение сильнее пробы: таймер не должен включить модули заново."""
        with self.lock:
            if self.active is not None:
                if self.timer is not None:
                    self.timer.cancel()
                    self.timer = None
                self._cancelled_id = self.active.get("id")
                self.active["phase"] = "cancelled"
                saved = False
                try:
                    self._save()
                    saved = True
                except OSError:
                    pass
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    if not saved:
                        self._finish("cancelled", "panic")
                        raise ChimeraError("err.trial.save") from None
                self._finish("cancelled", "panic")

    def _finish(self, phase, reason=None):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self.active["phase"], self.active["reason"] = phase, reason
        self.last, self.active = self.active, None
        self.changed()

    def _revert(self, reason):
        record = self.active
        if record is None:
            return
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        try:
            self.ops.restore(record["kind"], deepcopy(record["before"]))
            self.path.unlink(missing_ok=True)
        except Exception:
            record["phase"], record["reason"], record["error"] = "rollback_failed", reason, "err.trial.rollback"
            self.changed()
            return
        record.pop("error", None)
        self._finish("reverted", reason)

    def _expire(self, trial_id):
        with self.lock:
            if self.active is not None and self.active.get("id") == trial_id and self.active["phase"] == "pending":
                self._revert("timeout")

    def _check(self, trial_id, domains):
        def check(domain):
            try:
                data = self.ops.check(domain)
                return {"domain": domain, "status": data.get("status", "error"), "ms": data.get("ms")}
            except Exception:
                return {"domain": domain, "status": "error", "ms": None}

        with ThreadPoolExecutor(max_workers=len(domains)) as pool:
            results = list(pool.map(check, domains))
        with self.lock:
            if self.active is None or self.active.get("id") != trial_id or self.active["phase"] != "pending":
                return
            self.active["checks"], self.active["checks_done"] = results, True
            if self.now() >= self.deadline:
                self._revert("timeout")
            elif any(r["status"] not in ("ok", "challenge") for r in results):
                self._revert("check_failed")
            else:
                self.changed()
