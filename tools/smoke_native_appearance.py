"""Native WebView2 startup and live palette check on a disposable Windows runner."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def child(work):
    from modules import appconfig, domains, paths
    paths.migrate = lambda *args: None
    appconfig.CONFIG_PATH = work / "config.json"
    domains.LISTS_DIR = work / "lists"
    domains.LISTS_DIR.mkdir()
    from ui.api import Api
    from ui import backend_webview

    class CheckApi(Api):
        def dispatch(self, method, args_json):
            if self.is_read(method) or method in {"hub_snapshot", "hub_watch", "hub_refresh", "appearance_apply"}:
                return super().dispatch(method, args_json)
            return json.dumps({"ok": False, "error": "Operation outside native appearance check"})

    backend_webview.Api = lambda: CheckApi(service_owned=True)
    backend_webview.run()


def main():
    from tools.smoke_build import _free_port, _wait_cdp
    with tempfile.TemporaryDirectory(prefix="chimera-native-appearance-") as temporary:
        work = Path(temporary)
        port = _free_port()
        (work / "config.json").write_text(json.dumps({"auto_elevate": False, "lang": "ru", "update_check": False,
                                                     "close_to_tray": False, "theme": "dark",
                                                     "appearance": {"palette": "dracula"}}), encoding="utf-8")
        env = {**os.environ, "CHIMERA_DATA": str(work / "data"), "CHIMERA_SMOKE": "1",
               "QTWEBENGINE_REMOTE_DEBUGGING": str(port), "WEBVIEW2_USER_DATA_FOLDER": str(work / "profile"),
               "CHIMERA_INSTANCE_EVENT": rf"Local\Chimera_Native_Appearance_{os.getpid()}"}
        with (work / "engine.log").open("wb") as log:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(work)], cwd=ROOT,
                                    env=env, stdout=log, stderr=log)
            try:
                _wait_cdp(port, proc)
                result = subprocess.run(["node", str(ROOT / "tools/smoke_build.mjs"), str(port),
                                         str(ROOT / "tools/smoke_native_appearance.js")], capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=120)
                print(result.stdout)
                assert result.returncode == 0, result.stderr
                checks = json.loads(result.stdout.strip().splitlines()[-1])
                assert not checks["pageErrors"] and all(s["ok"] for s in checks["steps"]), checks
            finally:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                print((work / "engine.log").read_bytes()[-3000:].decode("utf-8", "replace"))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
    else:
        main()
