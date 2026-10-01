"""Exercise trial buttons and the real API with disposable files and simulated modules."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(screenshot=None):
    with tempfile.TemporaryDirectory(prefix="chimera-trial-ui-") as temporary:
        work = Path(temporary)
        os.environ.update(CHIMERA_DATA=str(work / "data"), CHIMERA_SMOKE="1", CHIMERA_LANG="ru")
        from modules import paths
        paths.migrate = lambda *args: None
        from modules import appconfig, domains
        appconfig.CONFIG_PATH = work / "config.json"
        appconfig.CONFIG_PATH.write_text(json.dumps({"auto_elevate": False, "lang": "ru", "update_check": False,
                                                    "theme": "dark"}), encoding="utf-8")
        domains.LISTS_DIR = work / "lists"
        domains.LISTS_DIR.mkdir()
        domains.save_raw("discord", "discord.com\n")
        from modules.winws import filters, manager
        filters.IPSET_FILE, filters.IPSET_BACKUP = work / "ipset.txt", work / "ipset.backup"
        manager.USER_HOSTLIST_PATH, manager.USER_IPSET_PATH = work / "user-hosts.txt", work / "user-ips.txt"
        from modules.hosts import manager as hosts_mod
        from ui import api as api_mod
        from ui.backend_browser import _Handler, _Hub
        hosts_mod.is_admin = api_mod.is_admin = lambda: True
        hosts_mod.resolve_domains = lambda names, *args: [{"host": domain, "ip": "127.0.0.2"} for domain in names]
        hub = _Hub()

        class CheckApi(api_mod.Api):
            def dispatch(self, method, args_json):
                if method == "__smoke_trial":
                    action = json.loads(args_json)[0]
                    if action in ("checks", "fail_checks"):
                        self._trial.ops.check = lambda domain: {"status": "blocked" if action == "fail_checks" else "ok"}
                        self.check_worker()
                    elif action == "expire":
                        self.clock[0] += 301
                        self.timer_callback()
                    return json.dumps({"ok": True, "data": {"trial": self._trial.state(), "winws": self.winws.state(),
                                                            "proxy_mode": self.proxy.config["mode"], "hosts": self.hosts.state()}})
                if self.is_read(method) or method in {"hub_snapshot", "hub_watch", "hub_refresh", "trial_start", "trial_confirm", "trial_revert"}:
                    return super().dispatch(method, args_json)
                return json.dumps({"ok": False, "error": "Operation outside trial check"})

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request, address):
                pass

        api = CheckApi(push=hub.push, service_owned=True)
        flags = {"winws": False, "proxy": False}
        api.clock = [0.0]
        api._trial.now = lambda: api.clock[0]
        api._trial.worker = lambda fn: setattr(api, "check_worker", fn)
        api._trial.schedule = lambda seconds, fn: setattr(api, "timer_callback", fn) or SimpleNamespace(cancel=lambda: None)
        api.winws._current = None
        api.winws.state = lambda: {**api.winws.config, "current": api.winws._current, "running": flags["winws"], "external": False}

        def start_strategy(sid):
            flags["winws"] = True
            api.winws._current = sid
            api.winws.config["last_strategy"] = sid
            api.winws._save()

        api.winws.start = start_strategy
        api.winws.stop = lambda: flags.update(winws=False)
        api.proxy.state = lambda: {**api.proxy.config, "running": flags["proxy"], "external": False, "core": {"present": True},
                                  "parsed": {"server": "server.example", "protocol": "vless"}}
        api.proxy.start = lambda: flags.update(proxy=True)
        api.proxy.stop = lambda: flags.update(proxy=False)
        api.proxy.set_mode = lambda value: api.proxy.config.update(mode=value) or api.proxy._save()
        api.hosts.hosts_path = work / "system-hosts"
        api.hosts.hosts_path.write_bytes(b"127.0.0.1 localhost\r\n# unmanaged\r\n")
        api.hosts._write_hosts = lambda text: api.hosts.hosts_path.write_bytes(text.encode("utf-8"))
        api.hosts._save_state({"enabled": False, "assignments": {"comss": ["discord"]}, "entries": []})
        api.hub.poke("winws", "proxy", "hosts")
        server = QuietServer(("127.0.0.1", 0), _Handler)
        server.api, server.hub, server.token = api, hub, "trial-test"
        server.web_dir, server.missing_next, server.daemon_threads = ROOT / "ui/web-next", False, True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            browser = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
            args = ["node", str(ROOT / "tools/smoke_http.mjs"), str(browser),
                    f"http://127.0.0.1:{server.server_address[1]}/?t=trial-test", str(ROOT / "tools/smoke_trials.js"), "trials"]
            if screenshot:
                args.append(str(Path(screenshot).resolve()))
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            print(result.stdout)
            assert result.returncode == 0, result.stderr
            checks = json.loads(result.stdout.strip().splitlines()[-1])
            assert not checks["pageErrors"] and all(step["ok"] for step in checks["steps"]), checks
            assert b"127.0.0.1 localhost\r\n# unmanaged\r\n" in api.hosts.hosts_path.read_bytes()
        finally:
            server.shutdown()
            server.server_close()
            api.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    main(parser.parse_args().screenshot)
