"""Exercise real appearance UI/API in headless Edge with disposable user files."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(screenshot=None):
    with tempfile.TemporaryDirectory(prefix="chimera-appearance-ui-") as temporary:
        work = Path(temporary)
        os.environ.update(CHIMERA_DATA=str(work / "data"), CHIMERA_SMOKE="1")
        from modules import appconfig, appearance, domains, paths
        paths.migrate = lambda *args: None
        appconfig.CONFIG_PATH = work / "config.json"
        appconfig.CONFIG_PATH.write_text(json.dumps({"auto_elevate": False, "lang": "ru", "update_check": False,
                                                    "theme": "system", "appearance": {"palette": "dracula"}}), encoding="utf-8")
        domains.LISTS_DIR = work / "lists"
        domains.LISTS_DIR.mkdir()
        from modules.winws import filters
        filters.IPSET_FILE, filters.IPSET_BACKUP = work / "ipset.txt", work / "ipset.backup"
        catalog = deepcopy(appearance.catalog())
        added = deepcopy(catalog["themes"][1])
        added["id"], added["name"] = "catalog-check", "Catalog check"
        remote = json.dumps({"schema": 1, "themes": [added]}).encode()
        refresh = appearance.refresh_catalog
        appearance.refresh_catalog = lambda: refresh(lambda url: remote)
        from ui.api import Api
        from ui.backend_browser import _Handler, _Hub
        hub = _Hub()
        from ui import theme
        system_mode = ["dark"]
        theme._system_theme = lambda: system_mode[0]

        class CheckApi(Api):
            def dispatch(self, method, args_json):
                if method == "__smoke_system_theme":
                    mode = json.loads(args_json)[0]
                    assert mode in ("light", "dark")
                    system_mode[0] = mode
                    return json.dumps({"ok": True, "data": mode})
                if self.is_read(method) or method in {"hub_snapshot", "hub_watch", "hub_refresh", "appearance_apply", "appearance_refresh"}:
                    return super().dispatch(method, args_json)
                return json.dumps({"ok": False, "error": "Operation outside appearance check"})

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request, address):
                pass

        api = CheckApi(push=hub.push, service_owned=True)
        server = QuietServer(("127.0.0.1", 0), _Handler)
        server.api, server.hub, server.token = api, hub, "appearance-test"
        server.web_dir, server.missing_next, server.daemon_threads = ROOT / "ui/web-next", False, True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            browser = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
            args = ["node", str(ROOT / "tools/smoke_http.mjs"), str(browser),
                    f"http://127.0.0.1:{server.server_address[1]}/?t=appearance-test", str(ROOT / "tools/smoke_appearance.js"), "appearance"]
            if screenshot:
                args.append(str(Path(screenshot).resolve()))
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            print(result.stdout)
            assert result.returncode == 0, result.stderr
            checks = json.loads(result.stdout.strip().splitlines()[-1])
            assert not checks["pageErrors"] and all(step["ok"] for step in checks["steps"]), checks
            from modules import configbackups
            assert any(item["kind"] == "auto" and item["valid"] for item in configbackups.list_backups())
            assert appconfig.load()["appearance_custom"]["appearance"]["name"] == "My checked theme"
        finally:
            server.shutdown()
            server.server_close()
            api.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    main(parser.parse_args().screenshot)
