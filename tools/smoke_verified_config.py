"""Check verified-snapshot buttons with the real API and disposable, simulated state."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(screenshot=None):
    with tempfile.TemporaryDirectory(prefix="chimera-verified-") as temporary:
        work = Path(temporary)
        os.environ.update(CHIMERA_DATA=str(work / "data"), CHIMERA_SMOKE="1", CHIMERA_LANG="ru")
        from modules import appconfig, domains, paths
        paths.migrate = lambda *args: None
        appconfig.CONFIG_PATH = work / "config.json"
        appconfig.CONFIG_PATH.write_text(json.dumps({"auto_elevate": False, "lang": "ru", "theme": "dark",
                                                    "update_check": False}), encoding="utf-8")
        domains.LISTS_DIR = work / "lists"
        domains.LISTS_DIR.mkdir()
        domains.save_raw("discord", "discord.com\n")
        from modules.winws import filters, manager
        filters.IPSET_FILE, filters.IPSET_BACKUP = work / "ipset.txt", work / "ipset.backup"
        manager.USER_HOSTLIST_PATH, manager.USER_IPSET_PATH = work / "user-hosts.txt", work / "user-ips.txt"
        from modules.hosts import manager as hosts_mod
        from ui import api as api_mod
        from ui.backend_browser import _Handler, _Hub
        from ui.trials import TrialOps
        hosts_mod.is_admin = api_mod.is_admin = lambda: True
        hub = _Hub()
        probe = {"status": "ok"}
        TrialOps.check = lambda self, name: {"status": probe["status"]}

        class CheckApi(api_mod.Api):
            def dispatch(self, method, args_json):
                if method == "__smoke_verified":
                    action = json.loads(args_json)[0]
                    if action == "fail":
                        probe["status"] = "blocked"
                    elif action == "change":
                        self.proxy.config["mode"] = "split"
                        self.proxy._save()
                    return json.dumps({"ok": True, "data": {"mode": self.proxy.config["mode"]}})
                return super().dispatch(method, args_json)

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request, address):
                pass

        api = CheckApi(push=hub.push, service_owned=True)
        for module in (api.winws, api.proxy, api.tg):
            type(module).running = property(lambda self: False)
            type(module)._ours_alive = property(lambda self: True)
        api.winws.state = lambda: {"running": False, "current": None, "external": False}
        api.proxy.state = lambda: {"running": False, "mode": api.proxy.config["mode"], "external": False}
        api.hosts.hosts_path = work / "system-hosts"
        api.hosts.hosts_path.write_bytes(b"127.0.0.1 localhost\r\n# unmanaged\r\n")
        api.hosts._write_hosts = lambda text: api.hosts.hosts_path.write_bytes(text.encode("utf-8"))
        api.hosts._save_state({"enabled": False, "assignments": {}, "entries": []})
        server = QuietServer(("127.0.0.1", 0), _Handler)
        server.api, server.hub, server.token = api, hub, "verified-test"
        server.web_dir, server.missing_next, server.daemon_threads = ROOT / "ui/web-next", False, True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            browser = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
            args = ["node", str(ROOT / "tools/smoke_http.mjs"), str(browser),
                    f"http://127.0.0.1:{server.server_address[1]}/?t=verified-test",
                    str(ROOT / "tools/smoke_verified_config.js"), "verified"]
            if screenshot:
                args.append(str(Path(screenshot).resolve()))
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            print(result.stdout)
            assert result.returncode == 0, result.stderr
            checks = json.loads(result.stdout.strip().splitlines()[-1])
            assert not checks["pageErrors"] and all(step["ok"] for step in checks["steps"]), checks
            assert api.hosts.hosts_path.read_bytes() == b"127.0.0.1 localhost\r\n# unmanaged\r\n"
        finally:
            server.shutdown()
            server.server_close()
            api.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    main(parser.parse_args().screenshot)
