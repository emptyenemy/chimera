"""Операции пробы: точное сохранение и восстановление затронутого модуля."""

from copy import deepcopy

from modules import blockcheck, configbackups
from modules.errors import ChimeraError
from modules.hosts.manager import BLOCK_RE
from ui.shareops import ShareOps


class TrialOps:
    def __init__(self, api):
        self.api = api

    def capture(self, kind, target):
        from ui.api import is_admin
        if not is_admin():
            raise ChimeraError("err.trial.admin")
        api = self.api
        if kind == "strategy":
            state = api.winws.state()
            if state.get("external"):
                raise ChimeraError("err.trial.external")
            if target not in {s["id"] for s in api.winws.strategies()}:
                raise ChimeraError("err.trial.arguments")
            before = {"running": bool(state.get("running")), "current": state.get("current"),
                      "last_strategy": api.winws.config.get("last_strategy")}
            if before["running"] and not before["current"]:
                raise ChimeraError("err.trial.external")
            section = "winws"
        elif kind == "tun":
            state = api.proxy.state()
            if state.get("external"):
                raise ChimeraError("err.trial.external")
            if target not in ("split", "tun"):
                raise ChimeraError("err.trial.arguments")
            before = {"running": bool(state.get("running")), "mode": api.proxy.config.get("mode", "pac")}
            section = "proxy"
        else:
            if target not in ("on", "off"):
                raise ChimeraError("err.trial.arguments")
            state = deepcopy(api.hosts._load_state())
            text = api.hosts._read_hosts()
            block = BLOCK_RE.search(text)
            before = {"state": state, "block": block.group() if block else None}
            section = "hosts"
        # Обычный снимок остаётся в истории и после завершения пробы.
        configbackups.create_snapshot(ShareOps(api).backup_state((section,), ()), kind="auto")
        return before

    def apply(self, kind, target):
        if kind == "strategy":
            self.api.winws.start(target)
        elif kind == "tun":
            self.api.proxy.stop()
            self.api.proxy.set_mode(target)
            self.api.proxy.start()
        else:
            self.api.hosts.set_enabled(target == "on")

    def restore(self, kind, before):
        from ui.api import is_admin
        if not is_admin():
            raise ChimeraError("err.trial.admin")
        api = self.api
        if kind == "strategy":
            if (set(before) != {"running", "current", "last_strategy"} or type(before["running"]) is not bool
                    or (before["running"] and not before["current"])
                    or any(value is not None and not isinstance(value, str) for value in (before["current"], before["last_strategy"]))):
                raise ChimeraError("err.trial.invalid_record")
            if api.winws.state().get("external"):
                raise ChimeraError("err.trial.external")
            api.winws.stop()
            if before["running"]:
                api.winws.start(before["current"])
            api.winws.config["last_strategy"] = before["last_strategy"]
            api.winws._save()
        elif kind == "tun":
            if (set(before) != {"running", "mode"} or type(before["running"]) is not bool
                    or before["mode"] not in ("pac", "split", "tun")):
                raise ChimeraError("err.trial.invalid_record")
            if api.proxy.state().get("external"):
                raise ChimeraError("err.trial.external")
            api.proxy.stop()
            api.proxy.set_mode(before["mode"])
            if before["running"]:
                api.proxy.start()
        else:
            if set(before) != {"state", "block"} or not isinstance(before["state"], dict):
                raise ChimeraError("err.trial.invalid_record")
            configbackups.normalize("hosts", before["state"])
            block = before["block"]
            if block is not None and (not isinstance(block, str) or not BLOCK_RE.fullmatch(block)):
                raise ChimeraError("err.trial.invalid_record")
            current = api.hosts._read_hosts()
            match = BLOCK_RE.search(current)
            if match:
                text = current[:match.start()] + (block or "") + current[match.end():]
            elif block:
                text = current + ("" if current.endswith(("\n", "\r")) else "\n") + block
            else:
                text = current
            if text != current:
                api.hosts._write_hosts(text)
            api.hosts._save_state(before["state"])

    def check(self, domain):
        return blockcheck.check(domain, socks_addr=self.api._proxy_socks_addr(domain))
