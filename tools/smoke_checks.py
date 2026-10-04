"""Exercise streamed website checks with disposable lists and simulated probes."""

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


def main():
    with tempfile.TemporaryDirectory(prefix="chimera-checks-ui-") as temporary:
        work = Path(temporary)
        os.environ.update(CHIMERA_DATA=str(work / "data"), CHIMERA_SMOKE="1", CHIMERA_LANG="ru")
        from modules import appconfig, domains, paths
        paths.migrate = lambda *args: None
        appconfig.CONFIG_PATH = work / "config.json"
        appconfig.CONFIG_PATH.write_text(json.dumps({"auto_elevate": False, "lang": "ru", "theme": "dark",
                                                    "update_check": False}), encoding="utf-8")
        domains.LISTS_DIR = work / "lists"
        domains.LISTS_DIR.mkdir()
        targets = [f"site-{index}.example" for index in range(1100)]
        domains.save_raw("bulk", "\n".join(targets))
        domains.save_raw("cloudflare", "speed.cloudflare.com" + chr(10) + "104.16.0.0/13" + chr(10))
        from modules.winws import filters, manager
        filters.IPSET_FILE, filters.IPSET_BACKUP = work / "ipset.txt", work / "ipset.backup"
        manager.USER_HOSTLIST_PATH, manager.USER_IPSET_PATH = work / "user-hosts.txt", work / "user-ips.txt"
        from ui import api as api_mod
        from ui.backend_browser import _Handler, _Hub
        delivery = threading.Event()
        delivery.set()
        finished = {"block": False, "rkn": False}
        checked = {"block": [], "rkn": []}
        manual = []

        class CheckHub(_Hub):
            def poll(self, cursor, timeout):
                result = super().poll(cursor, timeout)
                if not delivery.wait(15):
                    raise TimeoutError("Check event gate timed out")
                return result

        hub = CheckHub()

        class CheckApi(api_mod.Api):
            def chebur_status(self):
                return api_mod._ok({"version": "fixture"})

            def block_check_one(self, target):
                manual.append(target)
                return api_mod._ok(self._block_one(target))

            def chebur_check_one(self, target):
                return api_mod._ok(self._chebur_one(target))

            def _block_one(self, target):
                if target == "cf.example":   # настоящий _reach: адрес из сетей Cloudflare помечается
                    return super()._block_one(target)
                return {"target": target, "status": "dns" if target == "site-1.example" else "ok", "ms": 1}

            @staticmethod
            def _chebur_one(target):
                return {"target": target, "status": "ok", "blocked": target == "site-0.example", "rkn_domain": True}

            def block_check_start(self, name, request_id=None):
                result = super().block_check_start(name, request_id)
                if result["ok"]:
                    domains.save_raw(name, "changed-only.example\n")
                return result

            def _run_blockcheck(self, entries, request_id=None):
                checked["block"] = list(entries)
                super()._run_blockcheck(entries, request_id)
                finished["block"] = True

            def _run_chebur(self, entries, request_id=None):
                checked["rkn"] = list(entries)
                super()._run_chebur(entries, request_id)
                finished["rkn"] = True

            def dispatch(self, method, args_json):
                if method == "__smoke_checks":
                    action = json.loads(args_json)[0]
                    if action == "hold":
                        delivery.clear()
                    elif action == "release":
                        delivery.set()
                    elif action == "foreign":
                        self._push("blockResult", {"_request_id": "foreign", "target": "foreign.example", "status": "ok"})
                        self._push("blockDone", {"_request_id": "foreign", "results": []})
                    return json.dumps(api_mod._ok({"finished": dict(finished), "manual": list(manual),
                                                   "block": len(checked["block"]), "rkn": len(checked["rkn"]),
                                                   "events": hub._seq}))
                if self.is_read(method) or method in {"hub_snapshot", "hub_watch", "hub_refresh", "block_check_start",
                                                       "chebur_check_start", "proxy_set_lists"}:
                    return super().dispatch(method, args_json)
                return json.dumps({"ok": False, "error": "Operation outside checks test"})

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request, address):
                pass

        api_mod.blockcheck.check = lambda domain, socks_addr=None: {"target": domain, "status": "blocked",
                                                                    "ip": "104.16.1.1", "ms": 4000, "reason": "TLS"}
        # чужой и свой sing-box на этой машине не трогаем: прокси в проверке «не запущен»
        from modules.proxy.manager import ProxyManager
        ProxyManager._system_pids = staticmethod(lambda: [])
        ProxyManager._own_pids = lambda self: []
        api = CheckApi(push=hub.push, service_owned=True)
        api.proxy.config["mode"] = "split"
        api.winws.state = lambda: {**api.winws.config, "running": False, "external": False}
        api.proxy.state = lambda: {**api.proxy.config, "running": False, "external": False, "parsed": {"label": "fixture"},
                                   "all_lists": [item["name"] for item in domains.list_info()]}
        server = QuietServer(("127.0.0.1", 0), _Handler)
        server.api, server.hub, server.token = api, hub, "checks-test"
        server.web_dir, server.missing_next, server.daemon_threads = ROOT / "ui/web-next", False, True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            browser = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
            result = subprocess.run(["node", str(ROOT / "tools/smoke_http.mjs"), str(browser),
                                     f"http://127.0.0.1:{server.server_address[1]}/?t=checks-test",
                                     str(ROOT / "tools/smoke_sites.js"), "checks"], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=180)
            print(result.stdout)
            assert result.returncode == 0, result.stderr
            checks = json.loads(result.stdout.strip().splitlines()[-1])
            assert not checks["pageErrors"] and all(step["ok"] for step in checks["steps"]), checks
            assert checked["block"] == checked["rkn"] == targets
            assert domains.read_raw("bulk") == "changed-only.example\n"
        finally:
            delivery.set()
            server.shutdown()
            server.server_close()
            api.shutdown()


if __name__ == "__main__":
    main()
