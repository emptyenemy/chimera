"""Exercise the auto-setup page against the real API with a simulated network.

Сеть — модель из tests/autotune_net.py: YouTube открывается только со стратегией alt,
ChatGPT отказывает по стране и открывается через hosts comss, Discord открыт всегда.
Подбор можно задержать на проверке сайтов (hold/release), чтобы увидеть ход и отмену.
Система не меняется: ни winws, ни hosts, ни DNS не трогаются."""

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
    with tempfile.TemporaryDirectory(prefix="chimera-autotune-ui-") as temporary:
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
        for name, text in (("youtube", "youtube.com\ni.ytimg.com\n"), ("openai", "chatgpt.com\n"), ("discord", "discord.com\n")):
            domains.save_raw(name, text)
        from modules.autotune.manager import AutotuneManager
        from modules.hosts import manager as hosts_mod
        from tests.autotune_net import FakeOps, blocked_unless, opens
        from ui import api as api_mod
        from ui.backend_browser import _Handler, _Hub
        hosts_mod.is_admin = api_mod.is_admin = lambda: True
        hub = _Hub()
        gate = threading.Event()
        gate.set()

        net = FakeOps({"youtube": ["youtube.com", "i.ytimg.com"], "openai": ["chatgpt.com"], "discord": ["discord.com"]}, {
            "youtube.com": blocked_unless(lambda s: s["strategy"] == "alt", 80),
            "i.ytimg.com": blocked_unless(lambda s: s["strategy"] == "alt", 60),
            "chatgpt.com": blocked_unless(lambda s: s["hosts"].get("openai") == "comss", 120, status="denied"),
            "discord.com": opens(40),
        }, strategies=("general", "alt"), hosts=("xbox", "comss"), dns_plain=(), dns_unblock=())
        check = net.check
        net.check = lambda domain: (gate.wait(30), check(domain))[1]

        class CheckApi(api_mod.Api):
            def dispatch(self, method, args_json):
                if method == "__smoke_autotune":
                    action = json.loads(args_json)[0]
                    if action == "hold":
                        gate.clear()
                    elif action == "release":
                        gate.set()
                    return json.dumps({"ok": True, "data": {"net": net.state, "restored": len(net.restored)}})
                allowed = {"hub_snapshot", "hub_watch", "hub_refresh", "autotune_start", "autotune_cancel",
                           "autotune_revert", "autotune_keep"}
                if self.is_read(method) or method in allowed:
                    return super().dispatch(method, args_json)
                return json.dumps({"ok": False, "error": "Operation outside auto-setup check"})

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request, address):
                pass

        api = CheckApi(push=hub.push, service_owned=True)
        api._autotune = AutotuneManager(net, work / "autotune.json", api._mutation_lock,
                                        memory_path=work / "autotune-memory.json", changed=api._autotune_changed)
        server = QuietServer(("127.0.0.1", 0), _Handler)
        server.api, server.hub, server.token = api, hub, "autotune-test"
        server.web_dir, server.missing_next, server.daemon_threads = ROOT / "ui/web-next", False, True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            browser = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
            args = ["node", str(ROOT / "tools/smoke_http.mjs"), str(browser),
                    f"http://127.0.0.1:{server.server_address[1]}/?t=autotune-test", str(ROOT / "tools/smoke_autotune.js"),
                    "autotune"]
            if screenshot:
                args.append(str(Path(screenshot).resolve()))
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            print(result.stdout)
            assert result.returncode == 0, result.stderr
            checks = json.loads(result.stdout.strip().splitlines()[-1])
            assert not checks["pageErrors"] and all(step["ok"] for step in checks["steps"]), checks
        finally:
            gate.set()
            server.shutdown()
            server.server_close()
            api.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    main(parser.parse_args().screenshot)
