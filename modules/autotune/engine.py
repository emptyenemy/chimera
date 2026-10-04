"""Подбор способа обхода: диагноз, перебор по шагам, выбор лучшего варианта, отчёт.

Движок не знает про Windows: все изменения и проверки идут через ops (ui/autotune.py,
в тестах — модель сети). Порядок шагов — от безобидного к тяжёлому: стратегия winws
затрагивает только домены выбранных списков, hosts — только имена из списка, DNS —
весь компьютер, прокси — трафик через сервер пользователя. Подробности — docs/AUTOTUNE.md.
"""

import statistics
import threading
from concurrent.futures import ThreadPoolExecutor

from modules.autotune.targets import CANARY

OK_STATUSES = ("ok", "challenge")
STEPS = ("strategy", "hosts", "dns", "proxy")
MODES = ("fast", "smart")
# Умный режим сравнивает задержки: один проход слишком шумный, медиана трёх — уже нет.
ROUNDS = {"fast": 1, "smart": 3}
WORKERS = 16


class Cancelled(Exception):
    pass


def reason(status: str) -> str:
    """Причина недоступности словами движка: что из способов вообще может помочь."""
    return {"blocked": "dpi", "dns": "dns", "denied": "geo"}.get(status, "error")


def _median(values):
    return statistics.median(values) if values else None


class Engine:
    def __init__(self, ops, *, mode="fast", allowed=STEPS, memory=None, hints=None, exclude=None, progress=None,
                 cancel=None):
        if mode not in MODES:
            raise ValueError(mode)
        self.ops, self.mode = ops, mode
        self.allowed = tuple(s for s in STEPS if s in allowed)
        self.memory = memory or {}          # {сервис: {"kind": шаг, "id": вариант}} для этой сети
        self.hints = hints or {}            # {сервис: [{"kind", "id"}, ...]} — у того же провайдера
        # {шаг: [вариант, ...]} — что пользователь велел не пробовать: знает, что не поможет
        self.exclude = {step: set(ids) for step, ids in (exclude or {}).items()}
        self.progress = progress or (lambda event: None)
        self.cancel = cancel or threading.Event()
        self._targets = {}

    # --- проверки ---------------------------------------------------------------------

    def _stop_if_cancelled(self):
        if self.cancel.is_set():
            raise Cancelled()

    def _probe(self, domain):
        try:
            data = self.ops.check(domain) or {}
            return {"status": data.get("status", "error"), "ms": data.get("ms")}
        except Exception:
            return {"status": "error", "ms": None}

    def _check_domains(self, names, rounds):
        """Домен открыт, только если открылся во всех проходах; задержка — медиана."""
        results = {name: [] for name in names}
        for _ in range(rounds):
            self._stop_if_cancelled()
            with ThreadPoolExecutor(max_workers=max(1, min(WORKERS, len(names)))) as pool:
                for name, res in zip(names, pool.map(self._probe, names), strict=True):
                    results[name].append(res)
        merged = {}
        for name, runs in results.items():
            bad = [r for r in runs if r["status"] not in OK_STATUSES]
            ms = [r["ms"] for r in runs if r["status"] in OK_STATUSES and isinstance(r.get("ms"), (int, float))]
            merged[name] = {"status": bad[0]["status"] if bad else runs[0]["status"], "ms": _median(ms)}
        return merged

    def measure(self, services, rounds=None):
        """Состояние сервисов и контрольных сайтов при текущих настройках."""
        rounds = rounds or ROUNDS[self.mode]
        names = list(dict.fromkeys([d for s in services for d in self._targets[s]] + list(CANARY)))
        checked = self._check_domains(names, rounds)
        result = {"services": {}, "canary": {d: checked[d]["status"] in OK_STATUSES for d in CANARY}}
        for s in services:
            rows = [{"domain": d, **checked[d]} for d in self._targets[s]]
            good = [r for r in rows if r["status"] in OK_STATUSES]
            result["services"][s] = {
                "ok": len(good) == len(rows),
                "covered": len(good),
                "total": len(rows),
                "reasons": sorted({reason(r["status"]) for r in rows if r["status"] not in OK_STATUSES}),
                "ms": _median([r["ms"] for r in good if r["ms"] is not None]),
                "targets": rows,
            }
        return result

    def _load_targets(self, services):
        usable = []
        for s in services:
            if s not in self._targets:
                self._targets[s] = list(self.ops.targets(s))
            if self._targets[s]:
                usable.append(s)
        return usable

    def diagnose(self, services):
        """Только проверка, без изменений: что открывается и почему нет."""
        usable = self._load_targets(services)
        m = self.measure(usable, rounds=1)
        return {"services": [{"name": s, "targets": self._targets.get(s, []),
                              **(m["services"][s] if s in m["services"] else {"ok": None, "skipped": "no_targets"})}
                             for s in services],
                "canary": m["canary"], "offline": not any(m["canary"].values())}

    # --- выбор варианта ------------------------------------------------------------------

    @staticmethod
    def _key(m, goal):
        fixed = [s for s in goal if m["services"][s]["ok"]]
        covered = sum(m["services"][s]["covered"] for s in goal)
        ms = _median([m["services"][s]["ms"] for s in goal if m["services"][s]["ms"] is not None])
        # больше починенных сервисов, потом больше адресов, потом меньше задержка
        return (len(fixed), covered, -(ms if ms is not None else float("inf"))), fixed

    def _acceptable(self, m, protected, canary_ok):
        broken = [s for s in protected if not m["services"][s]["ok"]]
        lost = [d for d in canary_ok if not m["canary"].get(d)]
        if lost:
            return "canary"
        if broken:
            return "protected"
        return None

    @staticmethod
    def _improved(m, baseline, goal):
        """Сервисы, у которых вариант открыл больше адресов, чем было, — даже если не все."""
        return [s for s in goal if m["services"][s]["covered"] > baseline["services"][s]["covered"]]

    def _search(self, step, candidates, apply, goal, protected, canary_ok, baseline):
        """Перебирает варианты шага; возвращает (вариант, ключ, починенные, замер) лучшего или None."""
        best = None
        base_key = self._key(baseline, goal)[0][:2]
        for index, candidate in enumerate(candidates):
            self._stop_if_cancelled()
            self.progress({"type": "candidate", "step": step, "candidate": candidate,
                           "index": index, "total": len(candidates)})
            try:
                apply(candidate)
            except Exception as e:
                self.progress({"type": "result", "step": step, "candidate": candidate, "error": str(e) or type(e).__name__})
                continue
            self.ops.settle(step)
            m = self.measure(list(goal) + list(protected))
            rejected = self._acceptable(m, protected, canary_ok)
            key, fixed = self._key(m, goal)
            self.progress({"type": "result", "step": step, "candidate": candidate, "fixed": fixed,
                           "covered": key[1], "ms": None if key[2] == float("-inf") else -key[2],
                           "rejected": rejected})
            if rejected or key[:2] <= base_key:
                continue
            if best is None or key > best[1]:
                best = (candidate, key, fixed, m)
            if self.mode == "fast" and len(fixed) == len(goal):
                break
        return best

    def _ordered(self, step, candidates, goal):
        """Сначала то, что чинило в этой сети, потом сработавшее у того же провайдера, потом остальное."""
        remembered = [self.memory[s]["id"] for s in goal
                      if self.memory.get(s, {}).get("kind") == step and self.memory[s].get("id") in candidates]
        hinted = [h["id"] for s in goal for h in self.hints.get(s, ()) if h["kind"] == step and h["id"] in candidates]
        skip = self.exclude.get(step, set())
        return [c for c in dict.fromkeys(remembered + hinted + list(candidates)) if c not in skip]

    # --- шаги ------------------------------------------------------------------------------

    def _step_strategy(self, ctx):
        goal = [s for s in ctx["failing"] if set(ctx["state"]["services"][s]["reasons"]) & {"dpi", "error"}]
        if not goal:
            return {"step": "strategy", "skipped": "not_needed"}
        if self.ops.winws_external():
            return {"step": "strategy", "skipped": "external"}
        candidates = self._ordered("strategy", self.ops.strategies(), goal)
        if not candidates:
            return {"step": "strategy", "skipped": "no_candidates"}
        self.ops.prepare_strategy(goal)
        best = self._search("strategy", candidates, self.ops.apply_strategy, goal, ctx["protected"],
                            ctx["canary_ok"], ctx["state"])
        if best is None:
            self.ops.restore_strategy()
            return {"step": "strategy", "tried": len(candidates), "chosen": None}
        sid, _key, fixed, m = best
        self.ops.apply_strategy(sid)
        self.ops.settle("strategy")
        # список остаётся в winws и у частично открытого сервиса: иначе улучшение пропадёт
        self.ops.commit_strategy(self._improved(m, ctx["state"], goal))
        self._accept(ctx, "strategy", sid, fixed)
        return {"step": "strategy", "tried": len(candidates), "chosen": sid, "fixed": fixed}

    def _step_hosts(self, ctx):
        providers = self.ops.hosts_providers()
        if not providers:
            return {"step": "hosts", "skipped": "no_candidates"}
        chosen, tried = {}, 0
        for s in list(ctx["failing"]):
            original = self.ops.hosts_assignment(s)
            candidates = [p for p in self._ordered("hosts", providers, [s]) if p != original]
            tried += len(candidates)
            best = self._search("hosts", candidates, lambda p, s=s: self.ops.assign_hosts(s, p), [s],
                                ctx["protected"], ctx["canary_ok"], ctx["state"])
            if best is None:
                self.ops.assign_hosts(s, original)
                continue
            self.ops.assign_hosts(s, best[0])
            self.ops.settle("hosts")
            chosen[s] = best[0]
            self._accept(ctx, "hosts", best[0], [s])
        return {"step": "hosts", "tried": tried, "chosen": chosen or None}

    def _step_dns(self, ctx):
        if not self.ops.dns_available():
            return {"step": "dns", "skipped": "unavailable"}
        goal = list(ctx["failing"])
        reasons = {r for s in goal for r in ctx["state"]["services"][s]["reasons"]}
        plain = self.ops.dns_providers(unblock=False) if "dns" in reasons else []
        candidates = self._ordered("dns", plain + self.ops.dns_providers(unblock=True), goal)
        if not candidates:
            return {"step": "dns", "skipped": "no_candidates"}
        best = self._search("dns", candidates, self.ops.apply_dns, goal, ctx["protected"], ctx["canary_ok"], ctx["state"])
        if best is None:
            self.ops.revert_dns()
            return {"step": "dns", "tried": len(candidates), "chosen": None}
        self.ops.apply_dns(best[0])
        self.ops.settle("dns")
        self.ops.keep_dns()
        self._accept(ctx, "dns", best[0], best[2])
        return {"step": "dns", "tried": len(candidates), "chosen": best[0], "fixed": best[2]}

    def _step_proxy(self, ctx):
        if not self.ops.proxy_available():
            return {"step": "proxy", "skipped": "unavailable"}
        goal = list(ctx["failing"])
        best = self._search("proxy", ["proxy"], lambda _c: self.ops.apply_proxy(goal), goal,
                            ctx["protected"], ctx["canary_ok"], ctx["state"])
        if best is None:
            self.ops.restore_proxy()
            return {"step": "proxy", "tried": 1, "chosen": None}
        self.ops.commit_proxy(self._improved(best[3], ctx["state"], goal))
        self._accept(ctx, "proxy", "proxy", best[2])
        return {"step": "proxy", "tried": 1, "chosen": "proxy", "fixed": best[2]}

    def _accept(self, ctx, step, candidate, fixed):
        for s in fixed:
            ctx["fixes"][s] = {"kind": step, "id": candidate}
            ctx["failing"].remove(s)
            ctx["protected"].append(s)
        # следующий шаг сравнивает себя уже с новым положением дел
        ctx["state"] = self.measure(list(ctx["state"]["services"]))

    # --- целиком ----------------------------------------------------------------------------

    def run(self, services):
        usable = self._load_targets(services)
        self.progress({"type": "phase", "phase": "diagnose"})
        before = self.measure(usable)
        report = {"mode": self.mode, "before": before, "steps": [], "fixes": {}, "offline": False}
        canary_ok = [d for d, ok in before["canary"].items() if ok]
        if not canary_ok:
            # Не открывается даже контрольный сайт: сети нет, перебор ничего не даст.
            report["offline"] = True
            report["after"] = before
            return self._finish(report, services, usable)
        ctx = {"state": before, "failing": [s for s in usable if not before["services"][s]["ok"]],
               "protected": [s for s in usable if before["services"][s]["ok"]], "canary_ok": canary_ok,
               "fixes": report["fixes"]}
        steps = {"strategy": self._step_strategy, "hosts": self._step_hosts, "dns": self._step_dns,
                 "proxy": self._step_proxy}
        for step in self.allowed:
            if not ctx["failing"]:
                break
            self.progress({"type": "phase", "phase": step})
            report["steps"].append(steps[step](ctx))
        self.progress({"type": "phase", "phase": "verify"})
        report["after"] = self.measure(usable)
        return self._finish(report, services, usable)

    def _finish(self, report, services, usable):
        rows = []
        for s in services:
            if s not in usable:
                rows.append({"name": s, "skipped": "no_targets"})
                continue
            before, after = report["before"]["services"][s], report["after"]["services"][s]
            row = {"name": s, "before": before, "after": after, "fix": report["fixes"].get(s)}
            if not after["ok"]:
                row["hint"] = self._hint(after["reasons"], report)
            rows.append(row)
        report["services"] = rows
        return report

    def _hint(self, reasons, report):
        if report["offline"]:
            return "offline"
        proxy_step = next((s for s in report["steps"] if s.get("step") == "proxy"), None)
        if "geo" in reasons and (proxy_step is None or proxy_step.get("skipped")):
            return "need_proxy"
        if "dns" in reasons:
            return "dns"
        return "nothing_helped"
