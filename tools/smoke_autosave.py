"""Exercise queued UI saves with disposable files and a simulated Telegram module."""

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


def main(*, layout=False, screenshot=None, filters_only=False):
    with tempfile.TemporaryDirectory(prefix="chimera-autosave-ui-") as temporary:
        work = Path(temporary)
        os.environ.update(CHIMERA_DATA=str(work / "data"), CHIMERA_SMOKE="1", CHIMERA_LANG="ru")
        if layout:
            os.environ.pop("CHIMERA_LANG", None)
        from modules import paths
        paths.migrate = lambda *args: None
        from modules import appconfig, domains
        appconfig.CONFIG_PATH = work / "config.json"
        appconfig.CONFIG_PATH.write_text(json.dumps({"auto_elevate": False, "close_to_tray": False,
                                                    "lang": "ru", "theme": "dark", "update_check": False}), encoding="utf-8")
        if filters_only:
            appconfig.set_values({"game_filter": "all", "game_filter_tcp": "80", "game_filter_udp": "90"})
        domains.LISTS_DIR = work / "lists"
        domains.LISTS_DIR.mkdir()
        domains.save_raw("sample", "example.com\n")
        from modules.winws import filters, manager
        filters.IPSET_FILE, filters.IPSET_BACKUP = work / "ipset.txt", work / "ipset.backup"
        manager.USER_HOSTLIST_PATH, manager.USER_IPSET_PATH = work / "user-hosts.txt", work / "user-ips.txt"
        from ui import api as api_mod
        from ui.backend_browser import _Handler, _Hub
        hub = _Hub()
        tg = {"host": "127.0.0.1", "port": 19443, "secret": "ab" * 16, "autostart": False,
              "running": False, "installed": True, "fake_tls_domain": "example.org"}
        link_calls = []
        game_calls, game_failures = [], []
        failures = []
        probe = {"bypass": ["old.example"], "ad": "ad.example"}
        probe_failures, probe_reads = [], []
        dns_active = []  # адаптеры, где «стоит DNS программы»: питает точку у DNS в сайдбаре
        data_installed = []  # выпуск стратегий и списков поставлен
        sources = [{"name": name, "kind": "tag", "current": "1", "latest": "2", "update": True, "updatable": True}
                   for name in ("Source A", "Source B")]
        source_checks, source_updates = [], []
        release_check, release_update = threading.Event(), threading.Event()

        class CheckApi(api_mod.Api):
            def game_filter_set(self, mode, tcp=None, udp=None):
                game_calls.append([mode, tcp, udp])
                if tcp == "65000" and not game_failures:
                    game_failures.append(True)
                    return api_mod._err(OSError("Simulated range save failure"))
                return super().game_filter_set(mode, tcp, udp)

            def chebur_status(self):
                return api_mod._ok({"version": "fixture"})

            def hosts_ping_one(self, provider_id):
                return api_mod._ok({"ok": True, "ms": 1})

            def dns_state(self):
                return api_mod._ok({"adapters": [], "providers": []})

            def dns_status(self):
                return api_mod._ok({"active": list(dns_active)})

            def data_check(self):
                if data_installed:
                    return api_mod._ok({"current": "2026.10.05.1", "latest": "2026.10.05.1", "update": False,
                                        "installable": False, "plan": None, "min_app": "1.1.0", "error": None})
                return api_mod._ok({"current": "2026.10.01", "latest": "2026.10.05.1", "update": True, "installable": True,
                                    "plan": {"add": ["lists/new.txt"], "update": ["strategies/alt.txt"],
                                             "keep": ["lists/youtube.txt"], "same": 68},
                                    "min_app": "1.1.0", "error": None})

            def data_update(self):
                data_installed.append(True)
                return api_mod._ok({"version": "2026.10.05.1", "added": ["lists/new.txt"], "updated": ["strategies/alt.txt"],
                                    "kept": ["lists/youtube.txt"], "restarted": True, "apply_errors": []})

            def dns_probe_config(self):
                probe_reads.append(True)
                if len(probe_reads) == 1:
                    return api_mod._err(OSError("Simulated read failure"))
                return api_mod._ok(dict(probe))

            def dns_set_probe_config(self, bypass, ad):
                if "recover.example" in bypass and not probe_failures:
                    probe_failures.append(True)
                    return api_mod._err(OSError("Simulated probe save failure"))
                probe.update(bypass=bypass.lower().split(), ad=ad.lower().strip())
                return api_mod._ok(dict(probe))

            def upstream_versions(self):
                return api_mod._ok([{key: value for key, value in source.items() if key not in {"latest", "update"}}
                                   for source in sources])

            def upstream_check_updates(self, request_id=None):
                source_checks.append(True)
                snapshot = [dict(source) for source in sources]
                self._push("srcChecked", {**snapshot[0], "_request_id": request_id})
                if not release_check.wait(10):
                    return api_mod._err(TimeoutError("Source check gate timed out"))
                self._push("srcChecked", {**snapshot[1], "_request_id": request_id})
                return api_mod._ok(snapshot)

            def upstream_update(self, name):
                source_updates.append(name)
                if not release_update.wait(10):
                    return api_mod._err(TimeoutError("Source update gate timed out"))
                source = next(source for source in sources if source["name"] == name)
                source.update(current="2", update=False)
                return api_mod._ok(dict(source))

            def tg_state(self):
                return api_mod._ok(dict(tg))

            def tg_set_config(self, host, port, secret, autostart):
                if type(port) is not int or not 1 <= port <= 65535:
                    return api_mod._err(ValueError("Invalid port"))
                tg.update(host=host, port=port, secret=secret, autostart=autostart)
                return api_mod._ok(dict(tg))

            def tg_set_advanced(self, options):
                options = dict(options)
                for key in ("cfproxy_user_domains", "cfproxy_worker_domains"):
                    if isinstance(options.get(key), str):
                        options[key] = options[key].splitlines()
                tg.update(options)
                return api_mod._ok(dict(tg))

            def proxy_set_lists(self, names):
                if "queue-a" in names:
                    return api_mod._err(ValueError("Simulated connection failure"))
                self.proxy.config["lists"] = names
                return self.proxy_state()

            def proxy_set_link(self, value):
                if value.startswith("https://"):   # подписка — через настоящий менеджер с подменённой сетью
                    # заглушки fixture-* — не ссылки; снимок перед изменением отказался бы их сохранять
                    self.proxy._save({**self.proxy.config, "link": ""})
                    return super().proxy_set_link(value)
                link_calls.append(value)
                self.proxy.config["link"] = value
                return self.proxy_state()

            def lists_save(self, name, content):
                if "recover.example" in content and not failures:
                    failures.append(name)
                    return api_mod._err(OSError("Simulated disk failure"))
                return super().lists_save(name, content)

            def winws_set_lists(self, names):
                if "queue-a" in names:
                    return api_mod._err(ValueError("Simulated connection failure"))
                self.winws.config["lists"] = names
                return self.winws_state()

            def dispatch(self, method, args_json):
                if method == "__smoke_game":
                    return json.dumps(api_mod._ok({"calls": game_calls, "failures": len(game_failures)}))
                if method == "__smoke_sources":
                    action = json.loads(args_json)[0]
                    if action == "release-check":
                        release_check.set()
                    elif action == "release-update":
                        release_update.set()
                    return json.dumps(api_mod._ok({"checks": len(source_checks), "updates": len(source_updates)}))
                if method == "__smoke_dns_active":
                    dns_active[:] = json.loads(args_json)[0]
                    return json.dumps(api_mod._ok(list(dns_active)))
                if method == "__smoke_probe_failures":
                    return json.dumps(api_mod._ok(len(probe_failures)))
                if method == "__smoke_link_count":
                    return json.dumps(api_mod._ok(len(link_calls)))
                if method == "__smoke_failures":
                    return json.dumps(api_mod._ok(len(failures)))
                if method == "__smoke_record":
                    return json.dumps(api_mod._ok({"domains": [{"domain": "recorded.example", "hosts": []}], "seconds": 1}))
                if method == "dns_record_start":
                    return json.dumps(api_mod._ok({}))
                if method == "dns_record_stop":
                    return self.dispatch("__smoke_record", "[]")
                if self.is_read(method) or method in {"hub_snapshot", "hub_watch", "hub_refresh", "config_set",
                                                       "tg_set_config", "tg_set_advanced", "lists_save", "lists_create",
                                                       "lists_rename", "lists_delete", "proxy_set_lists", "winws_set_lists", "proxy_set_link",
                                                       "proxy_select_server", "proxy_fastest_server", "proxy_refresh_subscription",
                                                       "dns_set_probe_config", "upstream_update", "hosts_set_background", "game_filter_set",
                                                       "data_update"}:
                    return super().dispatch(method, args_json)
                return json.dumps({"ok": False, "error": "Operation outside autosave check"})

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request, address):
                pass

        api = CheckApi(push=hub.push, service_owned=True)
        api._restart_winws_if_running = lambda: None
        api.winws.state = lambda: {**api.winws.config, "running": False, "external": False, "all_lists": domains.available_lists()}
        api.proxy.state = lambda: {**api.proxy.config, "running": False, "external": False, "all_lists": domains.available_lists(),
                                  "parsed": {"server": "local.example", "protocol": "test", "security": "none", "label": "Fixture"},
                                  "servers": api.proxy._server_rows()}
        # sing-box пользователя (даже запущенный из этой же папки) не должен считаться нашим:
        # смена сервера перезапустила бы его. Подмена на классе — _own_pids смотрит туда
        type(api.proxy)._system_pids = staticmethod(lambda: [])
        type(api.proxy)._own_pids = staticmethod(lambda: [])
        from modules.proxy import subscription
        sub_links = ["vless://11111111-1111-1111-1111-111111111111@slow.example:443?security=tls#Slow",
                     "vless://22222222-2222-2222-2222-222222222222@fast.example:443?security=tls#Fast"]
        subscription.fetch = lambda url, opener=None: "\n".join(sub_links)
        subscription.ping_all = lambda servers, ping_fn=None: [{"Slow": 150, "Fast": 30}.get(s.rsplit("#", 1)[-1]) for s in servers]
        api.hub.poke("tg", "winws", "proxy")
        server = QuietServer(("127.0.0.1", 0), _Handler)
        server.api, server.hub, server.token = api, hub, "autosave-test"
        server.web_dir, server.missing_next, server.daemon_threads = ROOT / "ui/web-next", False, True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            browser = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
            scenario = "smoke_layout.js" if layout else "smoke_filters.js" if filters_only else "smoke_autosave.js"
            label = "layout" if layout else "filters" if filters_only else "autosave"
            args = ["node", str(ROOT / "tools/smoke_http.mjs"), str(browser),
                    f"http://127.0.0.1:{server.server_address[1]}/?t=autosave-test", str(ROOT / "tools" / scenario), label]
            if screenshot:
                args.append(str(Path(screenshot).resolve()))
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            assert result.returncode == 0, result.stderr or result.stdout
            checks = json.loads(result.stdout.strip().splitlines()[-1])
            if layout:
                failed = [step for step in checks["steps"] if not step["ok"]]
                report = {"passed": len(checks["steps"]) - len(failed), "total": len(checks["steps"]),
                          "failures": failed, "pageErrors": checks["pageErrors"]}
                print(json.dumps(report))
                assert not report["pageErrors"] and not failed, "Responsive layout checks failed"
            else:
                print(result.stdout)
                assert not checks["pageErrors"] and all(step["ok"] for step in checks["steps"]), checks
            if filters_only:
                assert filters.game_mode() == "udp"
                assert filters.game_ranges() == {"tcp": filters.GAME_RANGE_DEFAULT, "udp": "9400"}
                assert len(game_failures) == 1
            elif not layout:
                assert not (domains.LISTS_DIR / "sample.txt").exists()
                assert not (domains.LISTS_DIR / "renamed.txt").exists()
                assert "recorded.example" in domains.read_raw("queue-b")
                assert tg["port"] == 19444 and tg["autostart"]
                assert probe == {"bypass": ["recover.example"], "ad": "leave.example"}
                assert len(source_checks) == 1 and source_updates == ["Source A"]
                assert appconfig.load()["auto_elevate"] and appconfig.load()["close_to_tray"]
        finally:
            release_check.set()
            release_update.set()
            server.shutdown()
            server.server_close()
            api.shutdown()


if __name__ == "__main__":
    main()
