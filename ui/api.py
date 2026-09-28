"""Логика UI-режима: все методы, доступные фронтенду, без привязки к оконному движку.

Окно поднимает один из бэкендов (ui/backend_qt.py, ui/backend_webview.py) — оба
дёргают отсюда только dispatch() и подсовывают свой push() для стриминга в JS.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from modules import appconfig, autostart, blockcheck, cheburcheck, domains, upstream
from modules import discord as discord_cache
from modules.dns_jumper import DnsJumper
from modules.hosts import HostsManager
from modules.proxy import ProxyManager
from modules.tgproxy import TgProxy
from modules.winws import WinwsManager
from modules.hosts.manager import is_admin

WEB_DIR = Path(__file__).parent / "web"
VERSION = "1.0.0"


def _ok(data=None):
    return {"ok": True, "data": data}


def _err(e: Exception):
    return {"ok": False, "error": str(e)}


class Api:
    def __init__(self, push=None):
        # push(jsFnName, payload) — стриминг результатов в JS (см. _push).
        # Ставит бэкенд: у Qt это сигнал в QWebChannel, у pywebview — evaluate_js.
        self.push = push or (lambda fn, payload: None)
        self.hosts = HostsManager()
        self.hosts.start_background()  # автообновление/чекер/автопереключение hosts, см. modules/hosts/background.py
        self.dns = DnsJumper()
        self.tg = TgProxy()
        self.winws = WinwsManager()
        self.proxy = ProxyManager()
        # Автозапуски — в фоне: tg/winws/proxy поднимаются секундами (subprocess,
        # маршруты, TUN), и делать это до show() окна значит показывать пустой
        # экран всё это время. Дашборд подхватит их своим опросом, ошибки
        # приедут в UI через *_state, как и раньше.
        threading.Thread(target=self._autostart_all, daemon=True).start()

    def _autostart_all(self) -> None:
        if self.tg.config.get("autostart"):
            try:
                self.tg.start()
            except Exception:
                pass  # ошибка уедет в UI через tg_state
        if self.winws.config.get("autostart") and is_admin():
            try:
                self.winws.autostart()  # поднять последнюю стратегию
            except Exception:
                pass  # ошибка уедет в UI через winws_state
        if self.proxy.config.get("autostart"):
            try:
                self.proxy.start()
            except Exception:
                pass  # ошибка уедет в UI через proxy_state (часто — нет прав на TUN)

    def shutdown(self) -> None:
        """Гасит наши процессы при закрытии окна. Зовётся бэкендом явно: на atexit
        полагаться нельзя — интерпретатор не всегда доходит до его хендлеров, и
        winws2 (вместе с WinDivert) оставался висеть до перезагрузки."""
        self.hosts.stop_background()
        try:
            self.winws.stop()
        except Exception:
            pass
        try:
            self.proxy.stop()  # снять TUN/маршруты sing-box, иначе сеть «провиснет»
        except Exception:
            pass

    def app_info(self):
        return _ok({"admin": is_admin(), "version": VERSION})

    def upstream_versions(self):
        """Локальные версии источников (быстро, без сети)."""
        try:
            return _ok(upstream.versions())
        except Exception as e:
            return _err(e)

    def upstream_check_updates(self):
        """Сверить версии источников с GitHub (медленно — ходит в сеть).

        Каждый готовый источник сразу уезжает в UI через srcChecked — ждать
        самый медленный ответ (а это бывают секунды) ради остальных незачем.
        """
        try:
            return _ok(upstream.check_updates(lambda r: self._push("srcChecked", r)))
        except Exception as e:
            return _err(e)

    def upstream_check_one(self, name):
        """Сверить один источник — кнопка в его строке, без ожидания остальных."""
        try:
            return _ok(upstream.check_one(name))
        except Exception as e:
            return _err(e)

    def upstream_update(self, name):
        """Подтянуть свежую версию источника (git fetch + checkout/reset)."""
        try:
            return _ok(upstream.update_one(name))
        except Exception as e:
            return _err(e)

    def open_url(self, url):
        """Внешние ссылки из UI — в системный браузер."""
        try:
            if not str(url).startswith(("https://", "http://")):
                raise ValueError("Только http(s)-ссылки")
            import webbrowser
            webbrowser.open(url)
            return _ok()
        except Exception as e:
            return _err(e)

    def _push(self, fn: str, payload) -> None:
        """Зовёт JS-функцию window.<fn>(payload) — для стриминга результатов в UI.
        Безопасно звать из фоновых потоков: доставку в поток UI разруливает бэкенд."""
        self.push(fn, payload)

    def dispatch(self, method: str, args_json: str) -> str:
        """Единая точка входа для JS (см. ui/web/app.js: api()) — диспатчит по имени
        на обычные методы ниже, они как были — так и остались (_ok/_err, любые сигнатуры).
        Не заворачиваем каждый метод в отдельный слот моста: их ~60, и ни QWebChannel,
        ни js_api не умеют в произвольные *args/**kwargs — единый JSON-RPC проще.

        Вызывается из потока-воркера бэкенда, не из потока UI: почти каждый метод
        тут ходит в сеть или в subprocess (dns_state ~4 c, proxy_state ~1 c), и в
        UI-потоке это фризило бы окно на всё время вызова."""
        fn = getattr(self, method, None)
        if fn is None or method.startswith("_"):
            return json.dumps(_err(AttributeError(f"Неизвестный метод: {method}")))
        try:
            args = json.loads(args_json)
            return json.dumps(fn(*args))
        except Exception as e:
            return json.dumps(_err(e))

    # --- hosts -------------------------------------------------------------

    def hosts_overview(self):
        """Всё для вкладки: провайдеры, списки доменов и текущее состояние."""
        try:
            return _ok({
                "providers": self.hosts.providers(),
                "lists": domains.list_info(),
                "state": self.hosts.state(),
            })
        except Exception as e:
            return _err(e)

    def hosts_state(self):
        """Лёгкое состояние для дашборда (без провайдеров/списков)."""
        try:
            return _ok(self.hosts.state())
        except Exception as e:
            return _err(e)

    def hosts_ping_one(self, provider_id):
        try:
            return _ok(self.hosts.ping_one(provider_id))
        except Exception as e:
            return _err(e)

    def hosts_set_assignments(self, mapping):
        """Сохраняет привязки и СРАЗУ применяет (резолвит + пишет hosts)."""
        try:
            return _ok(self.hosts.set_assignments(mapping))
        except Exception as e:
            return _err(e)

    def hosts_set_enabled(self, value):
        """Общий выключатель hosts-разблокировки (привязки сохраняются)."""
        try:
            if not is_admin():
                raise PermissionError("Нужны права администратора для записи в hosts")
            return _ok(self.hosts.set_enabled(value))
        except Exception as e:
            return _err(e)

    def hosts_add_provider(self, name, doh, servers):
        try:
            return _ok(self.hosts.add_provider(name, doh, servers))
        except Exception as e:
            return _err(e)

    def hosts_delete_provider(self, provider_id):
        try:
            return _ok(self.hosts.delete_provider(provider_id))
        except Exception as e:
            return _err(e)

    def hosts_set_background(self, options):
        """Настройки фонового потока hosts: автообновление IP, TCP+TLS-чекер,
        автопереключение при деградации привязки (см. modules/hosts/background.py)."""
        try:
            return _ok(self.hosts.set_background(options))
        except Exception as e:
            return _err(e)

    # --- очистка кэша Discord (как пункт service.bat у Flowseal) -------------

    def discord_clear_cache(self):
        try:
            return _ok(discord_cache.clear_cache())
        except Exception as e:
            return _err(e)

    # --- dns jumper ----------------------------------------------------------

    def dns_state(self):
        try:
            return _ok({
                "adapters": self.dns.adapters(),
                "providers": self.dns.list_providers(),
            })
        except Exception as e:
            return _err(e)

    def dns_ping(self):
        try:
            return _ok(self.dns.ping_all())
        except Exception as e:
            return _err(e)

    def dns_ping_one(self, provider_id):
        try:
            return _ok(self.dns.ping_one(provider_id))
        except Exception as e:
            return _err(e)

    def dns_probe(self, provider_id):
        try:
            return _ok(self.dns.probe_provider(provider_id))
        except Exception as e:
            return _err(e)

    def dns_probe_config(self):
        try:
            return _ok(self.dns.probe_config())
        except Exception as e:
            return _err(e)

    def dns_set_probe_config(self, bypass, ad):
        try:
            return _ok(self.dns.set_probe_config(bypass, ad))
        except Exception as e:
            return _err(e)

    def dns_add_provider(self, name, servers, ipv6="", doh="", dot="", unblock=False, filtering=False):
        try:
            return _ok(self.dns.add_provider(name, servers, ipv6, doh, dot, unblock, filtering))
        except Exception as e:
            return _err(e)

    def dns_delete_provider(self, provider_id):
        try:
            self.dns.delete_provider(provider_id)
            return _ok()
        except Exception as e:
            return _err(e)

    def dns_set(self, adapter_index, provider_id):
        try:
            if not is_admin():
                raise PermissionError("Нужны права администратора для смены DNS")
            return _ok(self.dns.set_dns(adapter_index, provider_id))
        except Exception as e:
            return _err(e)

    def dns_reset(self, adapter_index):
        try:
            if not is_admin():
                raise PermissionError("Нужны права администратора для смены DNS")
            self.dns.reset_dns(adapter_index)
            return _ok()
        except Exception as e:
            return _err(e)

    # --- lists ---------------------------------------------------------------

    def lists_all(self):
        """Списки + пометки, через какой транспорт каждый идёт.

        lists/*.txt читают прокси (config["lists"]), hosts (assignments) и winws
        (config["lists"] -> list-general-user.txt). Список может идти сразу
        несколькими путями одновременно — это нормально, ничего не запрещаем.
        """
        try:
            info = domains.list_info()
            proxy_lists = set(self.proxy.config.get("lists") or [])
            winws_lists = set(self.winws.config.get("lists") or [])
            hosts_lists = set()
            for names in self.hosts.assignments().values():
                hosts_lists.update(names or [])
            for it in info:
                it["proxy"] = it["name"] in proxy_lists
                it["hosts"] = it["name"] in hosts_lists
                it["winws"] = it["name"] in winws_lists
            return _ok(info)
        except Exception as e:
            return _err(e)

    def lists_read(self, name):
        try:
            return _ok(domains.read_raw(name))
        except Exception as e:
            return _err(e)

    def lists_save(self, name, content):
        try:
            return _ok(domains.save_raw(name, content))
        except Exception as e:
            return _err(e)

    def lists_create(self, name):
        try:
            return _ok(domains.create_list(name))
        except Exception as e:
            return _err(e)

    def lists_delete(self, name):
        try:
            domains.delete_list(name)
            return _ok()
        except Exception as e:
            return _err(e)

    def lists_rename(self, old, new):
        """Переименовывает файл списка и переносит на новое имя все ссылки на
        него — иначе proxy/winws/hosts после ребилда конфига будут ссылаться
        на уже не существующее имя файла.
        """
        try:
            info = domains.rename_list(old, new)
            if old in (self.proxy.config.get("lists") or []):
                self.proxy.set_lists([new if n == old else n for n in self.proxy.config["lists"]])
            if old in (self.winws.config.get("lists") or []):
                self.winws.set_lists([new if n == old else n for n in self.winws.config["lists"]])
            assignments = self.hosts.assignments()
            if any(old in lists for lists in assignments.values()):
                patched = {pid: [new if n == old else n for n in lists] for pid, lists in assignments.items()}
                self.hosts.set_assignments(patched)
            return _ok(info)
        except Exception as e:
            return _err(e)

    # --- cheburcheck (проверка блокировок РКН) -------------------------------

    def chebur_status(self):
        try:
            return _ok(cheburcheck.status())
        except Exception as e:
            return _err(e)

    def chebur_check_one(self, domain):
        try:
            return _ok(cheburcheck.check(domain))
        except Exception as e:
            return _err(e)

    def chebur_check_start(self, name):
        """Гоняет домены списка через cheburcheck; результаты стримятся в UI."""
        try:
            entries = domains.load_lists([name])
        except Exception as e:
            return _err(e)
        if not entries:
            return _err(ValueError("В списке нет доменов"))
        threading.Thread(target=self._run_chebur, args=(entries,), daemon=True).start()
        return _ok({"total": len(entries)})

    def _run_chebur(self, domain_list):
        # умеренная параллельность: cheburcheck публичный, не долбим его
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self._chebur_one, d) for d in domain_list]
            for fut in as_completed(futures):
                self._push("cheburResult", fut.result())
        self._push("cheburDone", {})

    @staticmethod
    def _chebur_one(domain):
        try:
            return cheburcheck.check(domain)
        except Exception:
            return {"target": domain, "status": "error", "blocked": None}

    # --- blockcheck (локальная достижимость с этой машины) -------------------

    def _proxy_socks_addr(self, target: str) -> tuple[str, int] | None:
        """Адрес локального SOCKS5 нашего sing-box, ЕСЛИ домен реально уйдёт через
        него у пользователя прямо сейчас: режим PAC (в TUN это видно и так — см.
        modules/blockcheck.py), прокси запущен, домен попадает в один из его списков.
        Иначе None — обычная прямая проверка.
        """
        cfg = self.proxy.config
        if cfg.get("mode", "pac") == "tun" or not cfg.get("lists"):
            return None
        try:
            if not self.proxy.state().get("running"):
                return None
        except Exception:
            return None
        t = target.strip().lower().lstrip(".")
        dom, nets = domains.split_lists(cfg["lists"])
        hit = any(t == suffix or t.endswith("." + suffix) for suffix in dom)
        if not hit:
            # цель-IP считаем нашей, если она попадает в любую подсеть из списков —
            # то же правило, что уходит в PAC (isInNet) и в route-правило ip_cidr
            addr = domains.as_network(t)
            if addr is not None:
                hit = any(addr.subnet_of(net) for n in nets
                          if (net := domains.as_network(n)) is not None
                          and net.version == addr.version)
        if hit:
            return ("127.0.0.1", int(cfg.get("socks_port", 2080)))
        return None

    def block_check_one(self, domain):
        try:
            return _ok(blockcheck.check(domain, socks_addr=self._proxy_socks_addr(domain)))
        except Exception as e:
            return _err(e)

    def block_check_start(self, name):
        """Гоняет домены списка через локальный blockcheck; результаты стримятся в UI."""
        try:
            entries = domains.load_lists([name])
        except Exception as e:
            return _err(e)
        if not entries:
            return _err(ValueError("В списке нет доменов"))
        threading.Thread(target=self._run_blockcheck, args=(entries,), daemon=True).start()
        return _ok({"total": len(entries)})

    def _run_blockcheck(self, domain_list):
        # проверки локальные, без внешнего rate-limit — можно параллелить смелее
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(self._block_one, d) for d in domain_list]
            for fut in as_completed(futures):
                self._push("blockResult", fut.result())
        self._push("blockDone", {})

    def _block_one(self, domain):
        try:
            return blockcheck.check(domain, socks_addr=self._proxy_socks_addr(domain))
        except Exception:
            return {"target": domain, "status": "error", "ip": None, "ms": 0, "reason": None}

    # --- стратегии (winws2 / zapret2) -----------------------------------------

    def winws_state(self):
        try:
            return _ok({
                "strategies": self.winws.strategies(),
                **self.winws.state(),
            })
        except Exception as e:
            return _err(e)

    def winws_start(self, strategy_id):
        try:
            if not is_admin():
                raise PermissionError("Нужны права администратора для запуска zapret2")
            return _ok(self.winws.start(strategy_id))
        except Exception as e:
            return _err(e)

    def winws_stop(self):
        try:
            return _ok(self.winws.stop())
        except Exception as e:
            return _err(e)

    def winws_set_autostart(self, value):
        try:
            return _ok(self.winws.set_autostart(value))
        except Exception as e:
            return _err(e)

    def winws_set_lists(self, names):
        try:
            if self.winws.running and not is_admin():
                raise PermissionError("Нужны права администратора для перезапуска zapret2")
            return _ok(self.winws.set_lists(names))
        except Exception as e:
            return _err(e)

    def winws_log(self, offset=0):
        try:
            return _ok(self.winws.log_read(offset))
        except Exception as e:
            return _err(e)

    # --- фильтры winws2 (game / ipset, портированы с Flowseal) ----------------

    def filters_state(self):
        try:
            from modules.winws import filters
            return _ok(filters.state())
        except Exception as e:
            return _err(e)

    def game_filter_set(self, mode, tcp=None, udp=None):
        """mode — off/all/tcp/udp; tcp/udp — диапазоны портов (см. filters.validate_game_range),
        не переданы — старые значения не трогаем (обратная совместимость со старым вызовом
        одним аргументом)."""
        try:
            from modules.winws import filters
            filters.set_game_mode(mode)
            if tcp is not None or udp is not None:
                filters.set_game_ranges(tcp, udp)
            return _ok(filters.state())
        except Exception as e:
            return _err(e)

    def ipset_set(self, mode):
        try:
            from modules.winws import filters
            return _ok(filters.set_ipset_mode(mode))
        except Exception as e:
            return _err(e)

    def ipset_update(self):
        try:
            from modules.winws import filters
            return _ok(filters.update_ipset())
        except Exception as e:
            return _err(e)

    def fake_set(self, slot, name):
        """Подставляет блоб в ACTIVE_*-слот (Discord UDP / GameFilter UDP)."""
        try:
            from modules.winws import filters
            return _ok(filters.set_fake(slot, name))
        except Exception as e:
            return _err(e)

    # --- telegram proxy (tg-ws-proxy) -----------------------------------------

    def tg_state(self):
        try:
            return _ok(self.tg.state())
        except Exception as e:
            return _err(e)

    def tg_start(self):
        try:
            return _ok(self.tg.start())
        except Exception as e:
            return _err(e)

    def tg_stop(self):
        try:
            return _ok(self.tg.stop())
        except Exception as e:
            return _err(e)

    def tg_set_config(self, host, port, secret, autostart):
        try:
            return _ok(self.tg.set_config(host, port, secret, autostart))
        except Exception as e:
            return _err(e)

    def tg_regen_secret(self):
        try:
            return _ok(self.tg.regen_secret())
        except Exception as e:
            return _err(e)

    def tg_set_advanced(self, options):
        """Продвинутые настройки ядра (CF-proxy/worker домены, Fake TLS, dc-ip, ...).
        Применятся со следующего запуска прокси — см. TgProxy.set_advanced."""
        try:
            return _ok(self.tg.set_advanced(options))
        except Exception as e:
            return _err(e)

    def tg_log(self, offset=0):
        try:
            return _ok(self.tg.log_read(offset))
        except Exception as e:
            return _err(e)

    def tg_stats(self):
        try:
            return _ok(self.tg.live_stats())
        except Exception as e:
            return _err(e)

    def tg_check_update(self):
        try:
            return _ok(self.tg.check_update())
        except Exception as e:
            return _err(e)

    def tg_open_link(self):
        """Открывает tg://proxy в системе — Telegram сам предложит подключить."""
        try:
            import webbrowser
            link = self.tg.state().get("link")
            if not link:
                raise RuntimeError("Ссылка недоступна")
            webbrowser.open(link)
            return _ok()
        except Exception as e:
            return _err(e)

    # --- proxy (sing-box, выборочный по доменам) -----------------------------

    def proxy_state(self):
        try:
            return _ok(self.proxy.state())
        except Exception as e:
            return _err(e)

    def proxy_set_link(self, link):
        try:
            return _ok(self.proxy.set_link(link))
        except Exception as e:
            return _err(e)

    def proxy_set_lists(self, names):
        try:
            return _ok(self.proxy.set_lists(names))
        except Exception as e:
            return _err(e)

    def proxy_set_autostart(self, value):
        try:
            return _ok(self.proxy.set_autostart(value))
        except Exception as e:
            return _err(e)

    def proxy_download_core(self):
        try:
            return _ok(self.proxy.download_core())
        except Exception as e:
            return _err(e)

    def proxy_start(self):
        try:
            # админ нужен только для TUN; режим PAC (SOCKS) работает без прав
            if self.proxy.config.get("mode", "pac") == "tun" and not is_admin():
                raise PermissionError(
                    "Режим TUN требует прав администратора. Переключи на «Прокси (PAC)» "
                    "или запусти программу от админа."
                )
            return _ok(self.proxy.start())
        except Exception as e:
            return _err(e)

    def proxy_set_mode(self, mode):
        try:
            return _ok(self.proxy.set_mode(mode))
        except Exception as e:
            return _err(e)

    def proxy_stop(self):
        try:
            return _ok(self.proxy.stop())
        except Exception as e:
            return _err(e)

    def proxy_log(self, offset=0):
        try:
            return _ok(self.proxy.log_read(offset))
        except Exception as e:
            return _err(e)

    # --- settings (config.json) ---------------------------------------------

    def config_read(self):
        try:
            return _ok(appconfig.load())
        except Exception as e:
            return _err(e)

    def config_set(self, key, value):
        try:
            return _ok(appconfig.set_value(key, value))
        except Exception as e:
            return _err(e)

    def autostart_get(self):
        """Включён ли автозапуск приложения вместе с Windows (задача в планировщике)."""
        try:
            return _ok({"enabled": autostart.is_enabled(), "supported": autostart.is_supported()})
        except Exception as e:
            return _err(e)

    def autostart_set(self, value):
        """Создаёт/удаляет задачу автозапуска. Нужны права администратора."""
        try:
            if not is_admin():
                raise PermissionError("Нужны права администратора для настройки автозапуска")
            return _ok({"enabled": autostart.set_enabled(bool(value))})
        except Exception as e:
            return _err(e)
