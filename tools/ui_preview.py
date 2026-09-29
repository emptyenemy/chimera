"""Стенд для проверки интерфейса без окна программы.

Поднимает тот же сервер, что и движок `browser` (ui/backend_browser.py), с
настоящим Api — страницы видят реальное состояние модулей, — но:
  • автозапуски выключены (ничего не стартует само);
  • команды (всё, что не чтение) не исполняются: отвечают {"ok": true, "data": null}
    и печатаются в stdout с пометкой [команда] — видно, что кнопка дёрнула нужный метод;
  • браузер не открывается и сторож «вкладку закрыли — выходим» не запускается.

Режимы:
  python tools/ui_preview.py serve             — напечатать адрес и ждать (Ctrl+C)
  python tools/ui_preview.py shot OUT_DIR [СЦЕНАРИЙ.json]
      — headless Edge/Chrome по CDP (tools/ui_shot.mjs): по умолчанию обходит все
        страницы и снимает скриншоты в OUT_DIR; сценарий — список шагов, см. ui_shot.mjs.

Флаг --frontend legacy|next|all выбирает фронт: прежний (ui/web, по умолчанию), новый
(ui/web-next, нужна сборка: npm run build в frontend/) или оба подряд — снимки оба
фронта тогда ложатся в OUT_DIR/legacy и OUT_DIR/next.

Окно с интерфейсом при этом не появляется: браузер работает в headless-режиме
с отдельным временным профилем.
"""

import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ui import api as api_mod  # noqa: E402
from ui import frontend  # noqa: E402
from ui.backend_browser import _Handler, _Hub  # noqa: E402

# чтение определяет Api.is_read (глагол записи в имени перевешивает суффикс);
# сверху — служебные методы хаба, которые ничего не меняют
_SAFE = {"hub_snapshot", "hub_watch", "hub_refresh"}


from modules.hosts import HostsManager  # noqa: E402

# фон hosts (автообновление IP, чекер, автопереключение) пишет в настоящие
# data/hosts.json и системный hosts — на стенде ему не место
HostsManager.start_background = lambda self: None


class PreviewApi(api_mod.Api):
    def _autostart_all(self):
        pass

    def dispatch(self, method, args_json):
        if method in _SAFE or self.is_read(method):
            return super().dispatch(method, args_json)
        print(f"[команда] {method} {args_json}", flush=True)
        return json.dumps({"ok": True, "data": None})


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # headless-браузер рвёт long-poll при выходе — трейсы тут только шумят


def _serve(front: str = "legacy"):
    hub = _Hub()
    api = PreviewApi(push=hub.push)
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.api, server.hub, server.token = api, hub, "preview"
    server.web_dir = frontend.NEXT_DIR if front == "next" else frontend.LEGACY_DIR
    server.missing_next = front == "next" and not frontend.next_built()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/?t=preview"


def _browser() -> str | None:
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    return None


def _shot(front: str, out: Path, scenario: str) -> int:
    browser = _browser()
    if not browser:
        print("Не найден Edge/Chrome")
        return 1
    if front == "next" and not frontend.next_built():
        print(frontend.MISSING_TEXT)
        return 1
    server, url = _serve(front)
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["node", str(ROOT / "tools" / "ui_shot.mjs"), browser, url, str(out)]
    if scenario:
        cmd.append(str(Path(scenario).resolve()))
    try:
        return subprocess.call(cmd)
    finally:
        server.shutdown()


def main(argv):
    args = list(argv[1:])
    front = "legacy"
    if "--frontend" in args:
        i = args.index("--frontend")
        front = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if front not in ("legacy", "next", "all"):
        print("--frontend: legacy, next или all")
        return 1
    mode = args[0] if args else "serve"
    if mode == "serve":
        server, url = _serve("next" if front == "next" else "legacy")
        print(url, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    if mode == "shot":
        out = Path(args[1] if len(args) > 1 else "ui-shots").resolve()
        scenario = args[2] if len(args) > 2 else ""
        if front != "all":
            return _shot(front, out, scenario)
        codes = [_shot(f, out / f, scenario) for f in ("legacy", "next")]
        return max(codes)
    print(__doc__)
    return 1


if __name__ == "__main__":
    code = main(sys.argv)
    sys.stdout.flush()
    # пулы потоков Api (проверки, пинги) могут дорабатывать сетевые таймауты —
    # стенду их ждать незачем
    os._exit(code or 0)
