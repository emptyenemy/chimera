"""Логика UI-режима: все методы, доступные фронтенду, без привязки к оконному движку.

Окно поднимает один из бэкендов (ui/backend_qt.py, ui/backend_webview.py) — оба
дёргают отсюда только dispatch() и подсовывают свой push() для стриминга в JS.
"""

import inspect
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from pathlib import Path

from modules import (
    appconfig,
    appearance,
    applog,
    autostart,
    blockcheck,
    cheburcheck,
    control,
    configbackups,
    verifiedconfig,
    doctor,
    domainrec,
    domains,
    dns_providers,
    provider_registry,
    routeexplain,
    errors,
    i18n,
    filewatch,
    liveapply,
    paths,
    service,
    shareconfig,
    upstream,
    trials,
    winproc,
)
from modules import discord as discord_cache
from modules.errors import ChimeraError
from modules.dns_jumper import DnsJumper
from modules.hosts import HostsManager
from modules.proxy import ProxyManager
from modules.tgproxy import TgProxy
from modules.version import FLAVOR, VERSION
from modules.winws import WinwsManager
from modules.hosts.manager import is_admin
from ui.hub import StateHub
from ui.shareops import ShareOps
from ui.updater import Updater
from ui.trials import TrialOps
from ui.autotune import AutotuneOps
from modules.autotune.manager import AutotuneManager
from modules.autotune.watch import AutotuneWatch

WEB_DIR = Path(__file__).parent / "web-next"


def _ok(data=None):
    return {"ok": True, "data": data}


def _err(e: Exception):
    # error — русский текст, как отдавали раньше (старый фронт и агенты читают его);
    # code и params — для клиентов, которые собирают текст сами на выбранном языке
    return {"ok": False, **errors.describe(e)}


def _auto_snapshot(sections, list_args=()):
    def decorate(fn):
        signature = inspect.signature(fn)

        @wraps(fn)
        def wrapped(self, *args, **kwargs):
            try:
                bound = signature.bind(self, *args, **kwargs)
                bound.apply_defaults()
                with self._mutation_lock:
                    self._trial_guard(fn.__name__)
                    remote = self._backup_owner(fn.__name__, *list(bound.arguments.values())[1:])
                    if remote is not None:
                        return remote
                    if fn.__name__ in ("hosts_set_enabled", "winws_start") and not is_admin():
                        return fn(self, *args, **kwargs)
                    names = [bound.arguments[key] for key in list_args]
                    if any(not isinstance(name, str) or not domains.NAME_RE.fullmatch(name) for name in names):
                        return fn(self, *args, **kwargs)
                    with configbackups.automatic(lambda: ShareOps(self).backup_state(sections, names)):
                        return fn(self, *args, **kwargs)
            except Exception as e:
                return _err(e)
        return wrapped
    return decorate


def _backup_batch(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self._mutation_lock, configbackups.suspend_auto():
            return fn(self, *args, **kwargs)
    return wrapped


class Api:
    _mutation_lock = threading.RLock()

    def __init__(self, push=None, *, service_owned=False):
        self._service_owned = service_owned
        self._closed = False
        # push(jsFnName, payload) — стриминг результатов в JS (см. _push).
        # Ставит бэкенд: у Qt это сигнал в QWebChannel, у pywebview — evaluate_js.
        self.push = push or (lambda fn, payload: None)
        self.hosts = HostsManager()
        self.hosts.background.mutation_lock = self._mutation_lock
        self._smoke = os.environ.get("CHIMERA_SMOKE") == "1"
        self.dns = DnsJumper()
        self.tg = TgProxy()
        self.winws = WinwsManager()
        self.proxy = ProxyManager()
        self._trial = trials.TrialManager(TrialOps(self), paths.data_path("trial.json"), self._mutation_lock,
                                          changed=self._trial_changed, load_pending=service_owned or not service.is_running())
        owner = service_owned or not service.is_running()
        self._autotune = AutotuneManager(AutotuneOps(self), paths.data_path("autotune.json"), self._mutation_lock,
                                         changed=self._autotune_changed, load_pending=owner)
        self.hosts.background.can_mutate = lambda: self._trial.active is None and not self._autotune.blocks_changes()
        if owner:
            self._trial.recover()
            self._autotune.recover()
        if not self._smoke and self._trial.active is None and (service_owned or not service.is_running()):
            self.hosts.start_background()
        # Автозапуски — в фоне: tg/winws/proxy поднимаются секундами (subprocess,
        # маршруты, TUN), и делать это до show() окна значит показывать пустой
        # экран всё это время. Дашборд подхватит их своим опросом, ошибки
        # приедут в UI через *_state, как и раньше.
        # Если фоновая служба (modules/service.py) уже запущена — она единственный
        # владелец процессов, UI не поднимает свои автозапуски поверх неё.
        if not self._smoke and not service_owned and not service.is_running():
            threading.Thread(target=self._startup_then_autostart, daemon=True).start()
        if not self._smoke:
            threading.Thread(target=self._refresh_autostart_task, daemon=True).start()
        # Закрыть программу по её же команде (обновление): бэкенд подменяет на свой
        # выход через поток UI; по умолчанию — сразу, модули к этому моменту уже погашены.
        self.request_quit = lambda: os._exit(0)
        # Обновление программы: прогресс скачивания пушится хабом сразу, не по тику
        self.updater = Updater(on_change=lambda: getattr(self, "hub", None) and self.hub.poke("selfupdate"))
        self._bg_stop = threading.Event()
        self.updater.start_background(self._bg_stop)
        # Состояние модулей фронт больше не опрашивает сам — его пушит хаб (см. ui/hub.py).
        # lazy — только пока вкладку кто-то смотрит: dns_state это секунды PowerShell,
        # а живая статистика TG нужна лишь на её вкладке.
        self.hub = StateHub(lambda key, payload: self._push("hub", payload), [
            ("winws", self.winws_state, 2.0, False),
            ("proxy", self.proxy_state, 2.0, False),
            ("tg", self.tg_state, 2.0, False),
            ("hosts", self.hosts_state, 3.0, False),
            ("filters", self.filters_state, 15.0, True),
            ("tgStats", self.tg_stats, 1.0, True),
            ("dns", self.dns_state, 15.0, True),
            ("dnsStatus", self.dns_status, 5.0, False),
            ("selfupdate", self.selfupdate_state, 5.0, False),
            ("trial", self.trial_state, 1.0, False),
            ("autotune", self.autotune_state, 1.0, False),
        ])
        self.hub.start()
        # самолечение в фоне: по желанию (config.json -> autotune_watch), только у владельца модулей
        self._autotune_watch = AutotuneWatch(self._autotune, enabled=lambda: bool(appconfig.load().get("autotune_watch")),
                                             can_run=lambda: self._trial.active is None)
        if owner and not self._smoke:
            self._autotune_watch.start_background(self._bg_stop)
        if not self._smoke:
            self._watch_lists()

    def _watch_lists(self) -> None:
        """Правку lists/*.txt на диске (агентом, вручную) применяем так же, как lists_save.
        Следит владелец процессов: при работающей службе — она, окно молчит."""
        self.lists_watcher = filewatch.ListsWatcher(self._lists_file_changed,
                                                    active=lambda: getattr(self, "_service_owned", False) or not service.is_running())
        self.lists_watcher.start_background(self._bg_stop)

    def _lists_file_changed(self, kind, name) -> list:
        with self._mutation_lock:
            trial = getattr(self, "_trial", None)
            if trial is not None and trial.active is not None:
                self._trial_list_events = [*getattr(self, "_trial_list_events", []), (kind, name)]
                return [{"module": "trial", "error": str(ChimeraError("err.trial.busy"))}]
            autotune = getattr(self, "_autotune", None)
            if autotune is not None and autotune.busy():
                # подбор сам переписывает списки модулей; правку применим, когда он закончится
                self._trial_list_events = [*getattr(self, "_trial_list_events", []), (kind, name)]
                return [{"module": "autotune", "error": str(ChimeraError("err.autotune.busy"))}]
            errors = liveapply.apply_event(kind, name, self.winws, self.proxy, self.hosts)
        hub = getattr(self, "hub", None)
        if hub is not None:
            hub.poke("proxy", "hosts", "winws")  # счётчики доменов в выбранных списках
        return errors

    def _startup_then_autostart(self) -> None:
        # хвосты прошлого запуска убираем до автозапусков: поднятый ими прокси заново
        # поставит свой PAC, а чистка не должна принять его за чужой хвост
        self._startup_cleanup()
        self._autostart_all()

    def _startup_cleanup(self) -> None:
        """Убирает то, что осталось после аварийного завершения программы: системный
        PAC на мёртвый прокси. Фоновая служба — владелец модулей, при ней не трогаем.
        Ошибка чистки запуску не мешает."""
        try:
            if service.is_running():
                return
            if self.proxy.cleanup_stale_system_proxy():
                applog.write("Снят системный PAC-прокси, оставшийся от прошлого запуска: "
                             "прокси не работал, браузеры слали бы сайты на мёртвый порт")
        except Exception as e:
            applog.write(f"Очистка хвостов при запуске не удалась: {e}")

    def _autostart_all(self) -> None:
        # общая с service-режимом логика (modules/service.py) — ошибки одного
        # модуля не мешают остальным и уедут в UI через *_state, как и раньше.
        if self._trial.active is None and not self._autotune.blocks_changes():
            service.autostart_modules(self.tg, self.winws, self.proxy)

    @staticmethod
    def _refresh_autostart_task() -> None:
        # задача автозапуска из прошлой версии (без --tray или со старым путём к
        # программе) — пересоздать; без админа schtasks /Create не пройдёт, молча пропускаем
        if not is_admin():
            return
        try:
            autostart.refresh()
        except Exception:
            pass

    def shutdown(self) -> None:
        """Гасит наши процессы при закрытии окна. Зовётся бэкендом явно: на atexit
        полагаться нельзя — интерпретатор не всегда доходит до его хендлеров, и
        winws2 (вместе с WinDivert) оставался висеть до перезагрузки.

        Если рядом работает фоновая служба — она единственный владелец процессов
        (иначе закрытие окна погасило бы то, что служба должна держать поднятым);
        UI просто перестаёт опрашивать состояние и выходит."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        control.stop_current()  # `chimera ...` больше не должна видеть закрывающуюся программу
        self.hub.stop()
        self._bg_stop.set()
        watcher = getattr(self, "lists_watcher", None)
        if watcher is not None:
            watcher.stop()  # применение правки не должно идти к уже погашенным модулям
        self.hosts.stop_background()
        trial = getattr(self, '_trial', None)
        if trial is not None and (getattr(self, '_service_owned', False) or not service.is_running()):
            trial.recover()
        autotune = getattr(self, '_autotune', None)
        if autotune is not None and (getattr(self, '_service_owned', False) or not service.is_running()):
            autotune.recover()
        if getattr(self, "_smoke", False):
            self.tg.stop()
            return
        if service.is_running() and not getattr(self, "_service_owned", False):
            return
        try:
            self.winws.stop()
        except Exception:
            pass
        try:
            self.proxy.stop()  # снять TUN/маршруты sing-box, иначе сеть «провиснет»
        except Exception:
            pass
        try:
            self.tg.stop()
        except Exception:
            pass

    def panic_all(self):
        """«Выключить всё»: гасит обход, прокси, Telegram-прокси и службу, снимает подмену
        hosts, возвращает DNS на адаптерах, где его поставили мы, и убирает системный PAC.

        Шаги независимы: сбой одного (нет прав, занятый файл) остальным не мешает. Ответ —
        по шагу на строку: {step, ok, error?}. Модули и настройки остаются как были, поэтому
        включить всё обратно можно обычными переключателями."""
        trial = getattr(self, '_trial', None)
        autotune = getattr(self, '_autotune', None)

        def trial_step():
            if trial is not None:
                trial.abandon()

        def autotune_step():
            if autotune is not None:
                autotune.abandon()

        def service_step():
            if service.is_running():
                service.send_stop()

        def hosts_step():
            if not is_admin():
                raise ChimeraError("err.admin.hosts")
            self.hosts.set_enabled(False)

        def dns_step():
            adapters = self.dns.changed_adapters()
            if not adapters:
                return
            if not is_admin():
                raise ChimeraError("err.admin.dns_reset")
            failed_at, first_error = [], ""
            for idx in adapters:
                try:
                    self.dns.reset_dns(idx)
                except Exception as e:
                    failed_at.append(str(idx))
                    first_error = first_error or str(e)
            if failed_at:
                raise ChimeraError("err.panic.dns", count=len(failed_at), adapters=", ".join(failed_at),
                                   error=first_error)

        # служба первой: пока она жива, она перезапускала бы то, что мы гасим здесь.
        # Прокси останавливается до остального — его stop() заодно снимает системный PAC.
        steps = (("service", service_step), ("winws", self.winws.stop), ("proxy", self.proxy.stop),
                 ("tg", self.tg.stop), ("hosts", hosts_step), ("dns", dns_step))
        if trial is not None and trial.active is not None:
            steps = (("trial", trial_step), *steps)
        if autotune is not None and autotune.active is not None:
            steps = (("autotune", autotune_step), *steps)
        report = []
        for name, fn in steps:
            try:
                fn()
                report.append({"step": name, "ok": True})
            except Exception as e:
                report.append({"step": name, "ok": False, **errors.describe(e)})
        failed = [r for r in report if not r["ok"]]
        applog.write("Выключить всё: " + ("готово" if not failed else
                     "не удалось: " + "; ".join(f"{r['step']} ({r['error']})" for r in failed)))
        return _ok({"steps": report, "failed": len(failed)})

    # --- диагностика -----------------------------------------------------------

    def doctor_run(self):
        """Проверки «почему обход может не работать» (modules/doctor.py). Только чтение."""
        try:
            return _ok(doctor.evaluate(doctor.gather(self)))
        except Exception as e:
            return _err(e)

    def doctor_report(self, markdown=True):
        """Отчёт для issue: Markdown (по умолчанию) или те же данные, что у doctor_run.
        Ссылки прокси и секреты Telegram-прокси в отчёт не попадают."""
        try:
            res = doctor.evaluate(doctor.gather(self))
            return _ok(doctor.to_markdown(res) if markdown else res)
        except Exception as e:
            return _err(e)

    # --- запись доменов сайта -------------------------------------------------

    def dns_record_start(self, flush=True):
        """Начинает запись: запоминает имена в кэше DNS Windows. Открытый после этого сайт
        оставит в кэше имена, которые ему нужны (dns_record_stop вернёт разницу). Кэш перед
        записью сбрасывается (нужны права администратора), иначе домены, уже бывшие в нём,
        не покажутся."""
        try:
            flushed = False
            if flush and is_admin():
                domainrec.flush()
                flushed = True
            self._domain_rec = {"before": domainrec.read_cache(), "started": time.time(), "flushed": flushed}
            return _ok({"started": True, "flushed": flushed, "admin": is_admin()})
        except Exception as e:
            return _err(e)

    def dns_record_stop(self):
        """Заканчивает запись: домены, появившиеся в кэше DNS с начала, по основным доменам."""
        try:
            rec = getattr(self, "_domain_rec", None)
            if not rec:
                raise ChimeraError("err.record.not_started")
            after = domainrec.read_cache()
            self._domain_rec = None
            return _ok({"domains": domainrec.suggest(rec["before"], after), "flushed": rec["flushed"],
                        "seconds": round(time.time() - rec["started"])})
        except Exception as e:
            return _err(e)

    # --- обмен конфигом ---------------------------------------------------------

    def config_export(self, sections=None, list_names=None):
        """Конфиг для отправки: JSON-текст выбранных разделов (по умолчанию — переносимые,
        без настроек обхода DPI). Ссылки прокси и секретов в нём нет."""
        try:
            remote = self._backup_owner("config_export", sections, list_names)
            if remote is not None:
                return remote
            sections = [s for s in (sections or shareconfig.DEFAULT_SECTIONS) if s in shareconfig.SECTIONS]
            doc = shareconfig.build_export(ShareOps(self).snapshot(), sections, VERSION, list_names)
            return _ok(json.dumps(doc, ensure_ascii=False, indent=2))
        except Exception as e:
            return _err(e)

    def config_import_preview(self, text):
        """Что изменит чужой конфиг: по разделам — применится / пропущено / нужно подтверждение."""
        try:
            remote = self._backup_owner("config_import_preview", text)
            if remote is not None:
                return remote
            return _ok(shareconfig.preview(shareconfig.parse(text, VERSION), ShareOps(self).snapshot()))
        except Exception as e:
            return _err(e)

    @_backup_batch
    def config_import_apply(self, text, sections, confirmed=False):
        """Применяет выбранные разделы чужого конфига. Перед этим копирует затрагиваемые файлы
        в data/backups/<время>-import/. Чужие серверы DNS/hosts и домены-ретрансляторы Telegram
        ставятся только при confirmed=True."""
        try:
            remote = self._backup_owner("config_import_apply", text, sections, confirmed)
            if remote is not None:
                return remote
            ops = ShareOps(self)
            return _ok(shareconfig.apply(shareconfig.parse(text, VERSION), sections or [], bool(confirmed), ops))
        except Exception as e:
            return _err(e)

    def _backup_owner(self, method, *args):
        if not getattr(self, "_service_owned", False) and service.is_running():
            from modules.cli import client
            result = client.connect().api(method, *args)
            refresh = method in ("config_backup_restore", "config_import_apply", "config_set", "tg_regen_secret",
                                 "winws_start", "game_filter_set", "ipset_set", "ipset_update", "appearance_apply",
                                 "trial_start", "trial_confirm", "trial_revert",
                                 "autotune_start", "autotune_cancel", "autotune_revert", "autotune_keep")
            refresh |= method.startswith(("proxy_set_", "tg_set_", "winws_set_", "lists_", "hosts_", "dns_")) and not self.is_read(method)
            if refresh:
                self.proxy.config = self.proxy._load()
                self.winws.config = self.winws._load()
                # TgProxy._load can generate and save a secret; refresh here is read-only.
                from modules.tgproxy.manager import DEFAULTS as TG_DEFAULTS, STATE_PATH as TG_PATH
                try:
                    if TG_PATH.is_file():
                        self.tg.config = {**TG_DEFAULTS, **json.loads(TG_PATH.read_text(encoding="utf-8"))}
                except (OSError, ValueError, TypeError):
                    pass
                i18n.refresh()
                if getattr(self, "push", None):
                    with i18n.request_language(None):
                        self._push("langChanged", i18n.state())
                    if method in ("appearance_apply", "config_set", "config_backup_restore", "config_import_apply"):
                        self._push("appearanceChanged", appearance.state())
                hub = getattr(self, "hub", None)
                if hub is not None:
                    hub.poke("winws", "proxy", "tg", "hosts", "dns", "dnsStatus", "filters")
            return _ok(result)
        return None

    def config_backup_create(self, lang=None):
        try:
            with i18n.request_language(lang):
                remote = self._backup_owner("config_backup_create", lang)
                if remote is not None:
                    return remote
                with self._mutation_lock:
                    return _ok(configbackups.create_manual(ShareOps(self)))
        except Exception as e:
            return _err(e)

    def config_verify(self, selected, lang=None):
        try:
            with i18n.request_language(lang), self._mutation_lock:
                self._trial_guard("config_verify")
                remote = self._backup_owner("config_verify", selected, lang)
                if remote is not None:
                    return remote
                dns = getattr(self, "dns", None)
                if dns is not None and dns.trials():
                    raise ChimeraError("err.trial.busy")
                def context():
                    return {"modules": [{k: state.get(k) for k in ("running", "current", "mode", "external")}
                                        for state in (self.winws.state(), self.proxy.state())],
                            "hosts": self.hosts._read_hosts() if self.hosts.hosts_path.exists() else None}
                return _ok(verifiedconfig.create(ShareOps(self), selected, TrialOps(self).check, context))
        except Exception as e:
            return _err(e)

    def config_verified(self, lang=None):
        try:
            with i18n.request_language(lang):
                remote = self._backup_owner("config_verified", lang)
                return remote if remote is not None else _ok(verifiedconfig.state())
        except Exception as e:
            return _err(e)

    def config_backups(self, lang=None):
        try:
            with i18n.request_language(lang):
                remote = self._backup_owner("config_backups", lang)
                return remote if remote is not None else _ok(configbackups.list_backups())
        except Exception as e:
            return _err(e)

    def config_backup_compare(self, left_id, right_id, lang=None):
        try:
            with i18n.request_language(lang):
                remote = self._backup_owner("config_backup_compare", left_id, right_id, lang)
                return remote if remote is not None else _ok(configbackups.compare(left_id, right_id))
        except Exception as e:
            return _err(e)

    def config_backup_preview(self, backup_id, lang=None):
        try:
            with i18n.request_language(lang):
                remote = self._backup_owner("config_backup_preview", backup_id, lang)
                if remote is not None:
                    return remote
                with self._mutation_lock:
                    return _ok(configbackups.preview(backup_id, ShareOps(self)))
        except Exception as e:
            return _err(e)

    @_backup_batch
    def config_backup_restore(self, backup_id, confirmed=False, lang=None):
        try:
            with i18n.request_language(lang):
                remote = self._backup_owner("config_backup_restore", backup_id, confirmed, lang)
                if remote is not None:
                    return remote
                with self._mutation_lock:
                    trial = getattr(self, "_trial", None)
                    interrupted = trial is not None and trial.active is not None
                    if interrupted and trial.active["phase"] == "pending":
                        raise ChimeraError("err.trial.busy")
                    self._trial_restoring = interrupted
                    try:
                        result = configbackups.restore(backup_id, confirmed, ShareOps(self))
                        if interrupted and not result["errors"]:
                            trial.abandon()
                        return _ok(result)
                    finally:
                        self._trial_restoring = False
        except Exception as e:
            return _err(e)

    def app_elevate(self):
        from modules.elevation import relaunch
        started = relaunch(["--window", "--wait-ui-exit", str(os.getpid())])
        if started:
            # Let the response reach the button before closing the current window.
            timer = threading.Timer(0.5, self.request_quit)
            timer.daemon = True
            timer.start()
        return _ok({"started": started})

    def app_info(self):
        # Доступные движки зависят от варианта сборки; Git нужен только исходникам.
        return _ok({"admin": is_admin(), "version": VERSION, "service_running": service.is_running(),
                    "frozen": paths.IS_FROZEN, "flavor": FLAVOR,
                    "window_pids": getattr(self, "window_pids", lambda: [os.getpid()])(),
                    "ui_backends": (["pyside6", "pywebview", "browser"] if not paths.IS_FROZEN
                                    else {"qt": ["pyside6", "browser"], "webview": ["pywebview", "browser"],
                                          "lite": ["browser", "pywebview"]}[FLAVOR])})

    # --- обновление программы (ui/updater.py, modules/selfupdate.py) ----------

    def selfupdate_state(self):
        return _ok(self.updater.snapshot())

    def selfupdate_check(self):
        try:
            return _ok(self.updater.check())
        except Exception as e:
            return _err(e)

    def selfupdate_install(self):
        """Скачать, распаковать и поставить найденную версию; программа закроется и запустится снова."""
        try:
            return _ok(self.updater.install(shutdown=self.shutdown, request_quit=self.request_quit))
        except Exception as e:
            return _err(e)

    # --- хаб состояния (ui/hub.py) -------------------------------------------

    def hub_snapshot(self):
        """Всё уже известное состояние — для первого рендера, без ожидания опросов."""
        return _ok(self.hub.snapshot())

    def hub_watch(self, keys, on=True):
        """Вкладка открылась (on) / закрылась — включить/выключить ленивые источники."""
        self.hub.watch(keys, bool(on))
        return _ok()

    def hub_refresh(self, keys):
        """Перечитать источники вне очереди (кнопка «Обновить» и т.п.)."""
        self.hub.poke(*keys)
        return _ok()

    def upstream_versions(self):
        """Локальные версии источников (быстро, без сети)."""
        try:
            return _ok(upstream.versions())
        except Exception as e:
            return _err(e)

    def upstream_check_updates(self, request_id=None):
        """Сверить версии источников с GitHub (медленно — ходит в сеть).

        Каждый готовый источник сразу уезжает в UI через srcChecked — ждать
        самый медленный ответ (а это бывают секунды) ради остальных незачем.
        """
        try:
            def push_result(result):
                payload = {**result, "_request_id": request_id} if request_id is not None else result
                self._push("srcChecked", payload)
            return _ok(upstream.check_updates(push_result))
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
                raise ChimeraError("err.url.http_only")
            import webbrowser
            webbrowser.open(url)
            return _ok()
        except Exception as e:
            return _err(e)

    def _push(self, fn: str, payload) -> None:
        """Зовёт JS-функцию window.<fn>(payload) — для стриминга результатов в UI.
        Безопасно звать из фоновых потоков: доставку в поток UI разруливает бэкенд."""
        if fn == "appearanceChanged" and getattr(self, "_native_theme_changed", None):
            self._native_theme_changed(payload["styles"]["--background"])
        self.push(fn, payload)

    def dispatch(self, method: str, args_json: str) -> str:
        """Единая точка входа для JS (см. ui/web/js/core.js: api()) — диспатчит по имени
        на обычные методы ниже, они как были — так и остались (_ok/_err, любые сигнатуры).
        Не заворачиваем каждый метод в отдельный слот моста: их ~60, и ни QWebChannel,
        ни js_api не умеют в произвольные *args/**kwargs — единый JSON-RPC проще.

        Вызывается из потока-воркера бэкенда, не из потока UI: почти каждый метод
        тут ходит в сеть или в subprocess (dns_state ~4 c, proxy_state ~1 c), и в
        UI-потоке это фризило бы окно на всё время вызова."""
        fn = getattr(self, method, None)
        if fn is None or method.startswith("_"):
            return json.dumps(_err(ChimeraError("err.method.unknown", method=method)))
        try:
            args = json.loads(args_json)
            if self.is_read(method):
                return json.dumps(fn(*args))
            with self._mutation_lock:
                self._trial_guard(method)
                return json.dumps(fn(*args))
        except Exception as e:
            return json.dumps(_err(e))
        finally:
            self._poke_after(method)

    # префикс команды -> какие источники хаба она меняет
    _POKE = (
        (("winws_",), ("winws",)),
        (("filters_", "game_filter_", "ipset_", "fake_"), ("filters", "winws")),
        (("proxy_",), ("proxy",)),
        (("tg_",), ("tg", "tgStats")),
        (("hosts_",), ("hosts",)),
        (("dns_",), ("dns", "dnsStatus")),
        (("providers_",), ("dns", "hosts")),
        (("lists_",), ("proxy", "hosts", "winws")),  # счётчики доменов в выбранных списках
        (("selfupdate_",), ("selfupdate",)),
        (("trial_",), ("trial", "winws", "proxy", "hosts")),
        (("autotune_",), ("autotune", "winws", "proxy", "hosts", "dnsStatus")),
        (("panic_", "config_import_", "config_backup_restore"), ("winws", "proxy", "tg", "hosts", "dns", "dnsStatus", "filters")),
    )
    # чтения ничего не меняют — после них хаб не дёргаем
    _READ_SUFFIXES = ("_state", "_log", "_stats", "_overview", "_read", "_all", "_status",
                      "_ping", "_one", "_probe", "_probe_config", "_check_update", "_get",
                      "_info", "_versions", "_snapshot")
    # глагол записи в любом слове имени перевешивает суффикс: dns_set_probe_config
    # кончается на «читающий» _probe_config, но это запись в config.json
    _WRITE_WORDS = frozenset({"set", "add", "delete", "save", "create", "rename", "start",
                              "stop", "update", "download", "regen", "open", "clear",
                              "enabled", "install", "uninstall", "apply", "reset", "panic", "restore"})

    # сверка с апстримом — только сеть, хотя в имени и есть «update»
    _READ_NAMES = frozenset({"tg_check_update", "upstream_check_updates", "doctor_run", "doctor_report", "providers_list",
                             "config_export", "config_import_preview", "config_backups", "config_backup_preview", "config_backup_compare", "config_verified",
                              "appearance_preview", "route_explain", "lists_validate", "lists_index",
                              "autotune_catalog", "autotune_diagnose"})

    @classmethod
    def is_read(cls, method: str) -> bool:
        """Метод только читает (не меняет ни систему, ни настройки)."""
        if method in cls._READ_NAMES:
            return True
        if cls._WRITE_WORDS.intersection(method.split("_")):
            return False
        return method.endswith(cls._READ_SUFFIXES)

    def _poke_after(self, method: str) -> None:
        """После команды — перечитать затронутые источники, не дожидаясь их тика."""
        hub = getattr(self, "hub", None)
        if hub is None or self.is_read(method):
            return
        for prefixes, keys in self._POKE:
            if method.startswith(prefixes):
                hub.poke(*keys)

    # --- пробное применение -----------------------------------------------------

    def _trial_changed(self):
        hub = getattr(self, "hub", None)
        if hub is not None:
            hub.poke("trial", "winws", "proxy", "hosts")
        trial = getattr(self, "_trial", None)
        if trial is not None and trial.active is None:
            events, self._trial_list_events = getattr(self, "_trial_list_events", []), []
            for kind, name in events:
                try:
                    liveapply.apply_event(kind, name, self.winws, self.proxy, self.hosts)
                except Exception:
                    applog.write("Не удалось применить отложенную правку списка после пробы")

    def _trial_guard(self, method):
        self._autotune_guard(method)
        trial = getattr(self, "_trial", None)
        if getattr(self, "_trial_restoring", False):
            return
        if trial is None or method in ("trial_start", "trial_confirm", "trial_revert", "panic_all") or self.is_read(method):
            return
        state = self.trial_state()
        if not state.get("ok"):
            raise ChimeraError("err.trial.owner")
        active = state["data"].get("active")
        if method == "config_backup_restore" and active is not None and active["phase"] in ("invalid", "interrupted", "rollback_failed"):
            return
        if active is not None:
            raise ChimeraError("err.trial.busy")

    # --- автонастройка (docs/AUTOTUNE.md) ---------------------------------------------

    # autotune_start сам отказывает, если подбор уже идёт или прошлая сессия не закрыта
    _AUTOTUNE_FREE = ("autotune_start", "autotune_cancel", "autotune_revert", "panic_all")

    def _autotune_changed(self):
        hub = getattr(self, "hub", None)
        if hub is not None:
            hub.poke("autotune", "winws", "proxy", "hosts", "dnsStatus")
        autotune = getattr(self, "_autotune", None)
        if autotune is not None and not autotune.busy() and getattr(self, "_trial_list_events", None):
            self._trial_changed()   # отложенные во время подбора правки списков

    def _autotune_guard(self, method):
        autotune = getattr(self, "_autotune", None)
        if autotune is None or method in self._AUTOTUNE_FREE or self.is_read(method):
            return
        if getattr(self, "_service_owned", False) or not service.is_running():
            blocked = autotune.blocks_changes()
        else:
            state = self.autotune_state()
            if not state.get("ok"):
                raise ChimeraError("err.autotune.owner")
            active = state["data"].get("active")
            blocked = active is not None and active["phase"] in ("running", "interrupted", "invalid", "rollback_failed")
        if blocked:
            raise ChimeraError("err.autotune.busy")

    def autotune_state(self):
        try:
            remote = self._backup_owner("autotune_state")
            return remote if remote is not None else _ok(self._autotune.state())
        except Exception as e:
            return _err(e)

    def autotune_catalog(self):
        """Сервисы (списки) и адреса, по которым автонастройка их проверяет."""
        try:
            return _ok(self._autotune.catalog())
        except Exception as e:
            return _err(e)

    def autotune_diagnose(self, services=None):
        """Проверить сервисы при текущих настройках, ничего не меняя."""
        try:
            remote = self._backup_owner("autotune_diagnose", services)
            return remote if remote is not None else _ok(self._autotune.diagnose(services))
        except Exception as e:
            return _err(e)

    def autotune_start(self, services=None, mode="fast"):
        try:
            with self._mutation_lock:
                remote = self._backup_owner("autotune_start", services, mode)
                return remote if remote is not None else _ok(self._autotune.start(services, mode))
        except Exception as e:
            return _err(e)

    def autotune_cancel(self):
        try:
            remote = self._backup_owner("autotune_cancel")
            return remote if remote is not None else _ok(self._autotune.cancel())
        except Exception as e:
            return _err(e)

    def autotune_revert(self):
        try:
            remote = self._backup_owner("autotune_revert")
            return remote if remote is not None else _ok(self._autotune.revert())
        except Exception as e:
            return _err(e)

    def autotune_keep(self):
        try:
            remote = self._backup_owner("autotune_keep")
            return remote if remote is not None else _ok(self._autotune.keep())
        except Exception as e:
            return _err(e)

    def trial_state(self):
        try:
            remote = self._backup_owner("trial_state")
            return remote if remote is not None else _ok(self._trial.state())
        except Exception as e:
            return _err(e)

    def trial_start(self, kind, target, seconds=60, domains=None):
        try:
            with self._mutation_lock:
                remote = self._backup_owner("trial_start", kind, target, seconds, domains)
                return remote if remote is not None else _ok(self._trial.start(kind, target, seconds, domains))
        except Exception as e:
            return _err(e)

    def trial_confirm(self, trial_id):
        try:
            remote = self._backup_owner("trial_confirm", trial_id)
            return remote if remote is not None else _ok(self._trial.confirm(trial_id))
        except Exception as e:
            return _err(e)

    def trial_revert(self, trial_id):
        try:
            remote = self._backup_owner("trial_revert", trial_id)
            return remote if remote is not None else _ok(self._trial.revert(trial_id))
        except Exception as e:
            return _err(e)

    # --- hosts -------------------------------------------------------------

    def hosts_overview(self):
        """Всё для вкладки: провайдеры, списки доменов и текущее состояние."""
        try:
            return _ok({
                "providers": self.hosts.visible_providers(),
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

    @_auto_snapshot(('hosts',))
    def hosts_set_assignments(self, mapping):
        """Сохраняет привязки и СРАЗУ применяет (резолвит + пишет hosts)."""
        try:
            return _ok(self.hosts.set_assignments(mapping))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('hosts',))
    def hosts_set_enabled(self, value):
        """Общий выключатель hosts-разблокировки (привязки сохраняются)."""
        try:
            if not is_admin():
                raise ChimeraError("err.admin.hosts")
            return _ok(self.hosts.set_enabled(value))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('dns', 'hosts'))
    def hosts_add_provider(self, name, doh, servers):
        try:
            return _ok(self.hosts.add_provider(name, doh, servers))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('dns', 'hosts'))
    def hosts_delete_provider(self, provider_id):
        try:
            return _ok(self.hosts.delete_provider(provider_id))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('hosts',))
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
            trials = self.dns.trials()
            return _ok({
                "adapters": self.dns.adapters(),
                "providers": self.dns.list_providers(),
                # пробное применение в ожидании «Оставить / Вернуть»: одно (последнее) и все
                "trial": trials[-1] if trials else None,
                "trials": trials,
            })
        except Exception as e:
            return _err(e)

    def dns_status(self):
        """Лёгкая часть dns_state для точки в меню: где стоит поставленный нами DNS."""
        try:
            return _ok({"active": self.dns.active_adapters()})
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

    @_auto_snapshot(('config',))
    def dns_set_probe_config(self, bypass, ad):
        try:
            return _ok(self.dns.set_probe_config(bypass, ad))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('dns', 'hosts'))
    def dns_add_provider(self, name, servers, ipv6="", doh="", dot="", unblock=False, filtering=False):
        try:
            return _ok(self.dns.add_provider(name, servers, ipv6, doh, dot, unblock, filtering))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('dns', 'hosts'))
    def dns_delete_provider(self, provider_id):
        try:
            self.dns.delete_provider(provider_id)
            return _ok()
        except Exception as e:
            return _err(e)

    # --- провайдеры DNS и hosts: одно место настройки ------------------------------------

    def providers_list(self):
        """Все провайдеры, включая скрытые встроенные, и где они используются в hosts."""
        try:
            return _ok(provider_registry.listing(self.hosts.assignments()))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('dns', 'hosts'))
    def providers_add(self, name, servers, ipv6="", doh="", dot="", unblock=False, filtering=False):
        try:
            return _ok(dns_providers.add(name, servers=servers, ipv6=ipv6, doh=doh, dot=dot,
                                         unblock=unblock, filtering=filtering))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('dns', 'hosts'))
    def providers_update(self, provider_id, name, servers, ipv6="", doh="", dot="", unblock=False, filtering=False):
        """Правка своего провайдера; id не меняется, привязки hosts сохраняются."""
        try:
            provider = dns_providers.update(provider_id, name, servers=servers, ipv6=ipv6, doh=doh, dot=dot,
                                            unblock=unblock, filtering=filtering)
            self.hosts.provider_changed(provider_id)
            return _ok(provider)
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('dns', 'hosts'))
    def providers_delete(self, provider_id):
        try:
            return _ok(self.hosts.delete_provider(provider_id))  # снимает и привязки hosts
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('config',))
    def providers_hide(self, provider_id, hidden=True):
        """Встроенного удалить нельзя — вернётся с обновлением; скрываем со всех вкладок."""
        try:
            return _ok(provider_registry.set_hidden(provider_id, bool(hidden), self.hosts.assignments()))
        except Exception as e:
            return _err(e)

    def dns_set(self, adapter_index, provider_id):
        try:
            if not is_admin():
                raise ChimeraError("err.admin.dns")
            return _ok(self.dns.set_dns(adapter_index, provider_id))
        except Exception as e:
            return _err(e)

    def dns_set_trial(self, adapter_index, provider_id, seconds=15):
        """Как dns_set, но с автооткатом: если за `seconds` секунд DNS не подтвердили
        (dns_trial_confirm), адаптер возвращается к прежним настройкам. Откат идёт в
        бэкенде и не зависит от окна."""
        try:
            if not is_admin():
                raise ChimeraError("err.admin.dns")
            return _ok(self.dns.set_dns_trial(adapter_index, provider_id, seconds))
        except Exception as e:
            return _err(e)

    def dns_trial_confirm(self, adapter_index=None):
        """Оставить DNS после пробного применения (без аргумента — все ожидающие)."""
        try:
            return _ok(self.dns.trial_confirm(adapter_index))
        except Exception as e:
            return _err(e)

    def dns_trial_revert(self, adapter_index=None):
        """Не ждать таймера: вернуть прежний DNS сразу."""
        try:
            if not is_admin():
                raise ChimeraError("err.admin.dns")
            return _ok(self.dns.trial_revert(adapter_index))
        except Exception as e:
            return _err(e)

    def dns_reset(self, adapter_index):
        try:
            if not is_admin():
                raise ChimeraError("err.admin.dns")
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

    def lists_index(self):
        """Записи всех списков разом: поиск на странице проверки ищет по ним без запросов."""
        try:
            return _ok(domains.list_index())
        except Exception as e:
            return _err(e)

    def route_explain(self, target, app=None):
        try:
            target, _addr = routeexplain.normalize_target(target)
            app = routeexplain.normalize_app(app)
            remote = self._backup_owner('route_explain', target, app)
            if remote is not None:
                return remote
            return _ok(routeexplain.explain(target, app=app,
                proxy_config=self.proxy.config, proxy_state=self.proxy.state(),
                winws_config=self.winws.config, winws_state=self.winws.state(),
                hosts_state=self.hosts.state(), hosts_path=self.hosts.hosts_path))
        except Exception as e:
            return _err(e)

    def lists_validate(self, name=None):
        try:
            remote = self._backup_owner('lists_validate', name)
            return remote if remote is not None else _ok(domains.validate_lists(name))
        except Exception as e:
            return _err(e)

    def lists_read(self, name):
        try:
            return _ok(domains.read_raw(name))
        except Exception as e:
            return _err(e)

    @_auto_snapshot((), ('name',))
    def lists_save(self, name, content):
        """Сохраняет список и сразу применяет его везде, где он подключён.
        Ошибка применения (например, нет прав на hosts) не отменяет сохранение —
        она приезжает рядом в apply_errors."""
        try:
            data = domains.save_raw(name, content)
            data["apply_errors"] = self._lists_changed(name)
            return _ok(data)
        except Exception as e:
            return _err(e)

    def lists_apply(self, name=None):
        """Явно применяет содержимое списка (без имени — всех) к winws, прокси и hosts: то же,
        что делает lists_save и наблюдатель за файлами. Ошибки модулей — в apply_errors."""
        try:
            if name:
                domains.read_raw(name)  # нет такого списка — ошибка, а не молчаливое «применено»
            names = [name] if name else domains.available_lists()
            return _ok({"applied": names,
                        "modules": liveapply.consumers(names, self.winws, self.proxy, self.hosts),
                        "apply_errors": liveapply.lists_changed(names, self.winws, self.proxy, self.hosts)})
        except Exception as e:
            return _err(e)

    @_auto_snapshot((), ('name',))
    def lists_create(self, name):
        try:
            return _ok(domains.create_list(name))  # новый список пока никуда не подключён
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('proxy', 'winws', 'hosts'), ('name',))
    def lists_delete(self, name):
        try:
            domains.delete_list(name)
            # удалённый список не должен оставаться в подключениях
            return _ok({"apply_errors": liveapply.lists_removed(name, self.winws, self.proxy, self.hosts)})
        except Exception as e:
            return _err(e)

    # --- применение изменений на лету ---------------------------------------
    # Правка не должна требовать от пользователя ручных перезапусков: где модуль
    # умеет подхватить изменение сам (файлы правил sing-box, hostlist winws2) — просто
    # обновляем файлы; где без перезапуска нельзя (игровой фильтр, блоб, настройки
    # ядра Telegram) — перезапускаем модуль сами, если он запущен.

    # Сама логика применения к winws/proxy/hosts — в modules/liveapply.py: её же зовёт
    # наблюдатель за файлами в службе, где Api нет.

    def _lists_changed(self, name) -> list:
        """Применяет изменившееся содержимое списка к тем, кто его использует.
        Возвращает ошибки применения [{"module", "error"}] — сохранение они не ломают."""
        return liveapply.lists_changed([name], self.winws, self.proxy, self.hosts)

    def _restart_winws_if_running(self) -> None:
        """Перезапускает текущую стратегию, если winws запущен: игровой фильтр и
        блобы winws2 читает только при старте."""
        sid = self.winws._current or self.winws.config.get("last_strategy")
        if not (self.winws.running and sid):
            return
        if not self.winws._ours_alive:
            # остался от прошлой сессии: какую стратегию он гоняет, мы не знаем
            raise ChimeraError("err.winws.foreign")
        if not is_admin():
            raise ChimeraError("err.admin.winws_restart")
        self.winws.start(sid)

    @_auto_snapshot(('proxy', 'winws', 'hosts'), ('old', 'new'))
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

    def chebur_check_start(self, name, request_id=None, targets=None):
        """Гоняет домены списка через cheburcheck; результаты стримятся в UI."""
        try:
            if targets is not None:
                if not isinstance(targets, list) or not all(isinstance(item, str) and item for item in targets):
                    raise TypeError("targets must be a list of nonempty strings")
                entries = list(dict.fromkeys(targets))
            else:
                entries = domains.load_lists([name])
        except Exception as e:
            return _err(e)
        if not entries:
            return _err(ChimeraError("err.list.empty"))
        threading.Thread(target=self._run_chebur, args=(entries, request_id), daemon=True).start()
        return _ok({"total": len(entries)})

    def _run_chebur(self, domain_list, request_id=None):
        # умеренная параллельность: cheburcheck публичный, не долбим его
        results = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self._chebur_one, d) for d in domain_list]
            for fut in as_completed(futures):
                result = fut.result()
                payload = {**result, "_request_id": request_id} if request_id is not None else result
                results.append(result)
                self._push("cheburResult", payload)
        done = {"_request_id": request_id, "results": results} if request_id is not None else {}
        self._push("cheburDone", done)

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
        if self.proxy.needs_admin or not cfg.get("lists"):  # TUN — проверка и так пойдёт через него
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

    def block_check_start(self, name, request_id=None):
        """Гоняет домены списка через локальный blockcheck; результаты стримятся в UI."""
        try:
            entries = domains.load_lists([name])
        except Exception as e:
            return _err(e)
        if not entries:
            return _err(ChimeraError("err.list.empty"))
        threading.Thread(target=self._run_blockcheck, args=(entries, request_id), daemon=True).start()
        return _ok({"total": len(entries), "targets": entries} if request_id is not None else {"total": len(entries)})

    def _run_blockcheck(self, domain_list, request_id=None):
        # проверки локальные, без внешнего rate-limit — можно параллелить смелее
        results = []
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(self._block_one, d) for d in domain_list]
            for fut in as_completed(futures):
                result = fut.result()
                payload = {**result, "_request_id": request_id} if request_id is not None else result
                results.append(result)
                self._push("blockResult", payload)
        done = {"_request_id": request_id, "results": results} if request_id is not None else {}
        self._push("blockDone", done)

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

    @_auto_snapshot(('winws',))
    def winws_start(self, strategy_id):
        try:
            if not is_admin():
                raise ChimeraError("err.admin.winws")
            return _ok(self.winws.start(strategy_id))
        except Exception as e:
            return _err(e)

    def winws_stop(self):
        try:
            return _ok(self.winws.stop())
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('winws',))
    def winws_set_autostart(self, value):
        try:
            return _ok(self.winws.set_autostart(value))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('winws',))
    def winws_set_lists(self, names):
        try:
            return _ok(self.winws.set_lists(names))  # без перезапуска — права не нужны
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

    @_auto_snapshot(('config',))
    def game_filter_set(self, mode, tcp=None, udp=None):
        """mode — off/all/tcp/udp; tcp/udp — диапазоны портов (см. filters.validate_game_range),
        не переданы — старые значения не трогаем (обратная совместимость со старым вызовом
        одним аргументом)."""
        try:
            from modules.winws import filters
            filters.set_game_config(mode, tcp, udp)
            data = filters.state()
            # порты игрового фильтра winws2 берёт при старте — запущенный перезапускаем сам
            self._apply_and_report(data, self._restart_winws_if_running)
            return _ok(data)
        except Exception as e:
            return _err(e)

    @staticmethod
    def _apply_and_report(data: dict, fn) -> None:
        """Выполняет применение; сбой не отменяет сохранённую настройку, а кладётся
        в data["apply_error"] — фронт покажет его рядом."""
        try:
            fn()
        except Exception as e:
            info = errors.describe(e)
            data["apply_error"] = info["error"]
            data["apply_error_code"], data["apply_error_params"] = info["code"], info["params"]

    @_auto_snapshot(('filters',))
    def ipset_set(self, mode):
        try:
            from modules.winws import filters
            return _ok(filters.set_ipset_mode(mode))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('filters',))
    def ipset_update(self):
        try:
            from modules.winws import filters
            return _ok(filters.update_ipset())
        except Exception as e:
            return _err(e)

    def fake_set(self, slot, name):
        """Подставляет блоб в ACTIVE_*-слот (Discord UDP / GameFilter UDP). Блоб winws2
        читает при старте, поэтому запущенную стратегию перезапускаем сами."""
        try:
            from modules.winws import filters
            data = filters.set_fake(slot, name)
            self._apply_and_report(data, self._restart_winws_if_running)
            return _ok(data)
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

    @_auto_snapshot(('telegram',))
    def tg_set_config(self, host, port, secret, autostart):
        try:
            return _ok(self.tg.set_config(host, port, secret, autostart))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('telegram',))
    def tg_regen_secret(self):
        try:
            return _ok(self.tg.regen_secret())
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('telegram',))
    def tg_set_advanced(self, options):
        """Продвинутые настройки ядра (CF-proxy/worker домены, Fake TLS, dc-ip, ...).
        Ядро читает их при старте, поэтому запущенный прокси перезапускается сам."""
        try:
            data = self.tg.set_advanced(options)
            if data.pop("restart_required", False):
                self._apply_and_report(data, self.tg.restart)
            return _ok(data)
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
                raise ChimeraError("err.tg.no_link")
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

    @_auto_snapshot(('proxy',))
    def proxy_set_link(self, link):
        try:
            return _ok(self.proxy.set_link(link))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('proxy',))
    def proxy_set_lists(self, names):
        try:
            return _ok(self.proxy.set_lists(names))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('proxy',))
    def proxy_set_apps(self, names):
        try:
            return _ok(self.proxy.set_apps(names))
        except Exception as e:
            return _err(e)

    def proxy_apps_snapshot(self):
        """Запущенные программы сессии пользователя — для выбора в выборочный TUN."""
        try:
            return _ok(winproc.user_apps())
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('proxy',))
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
            # админ нужен только для TUN (выборочного и полного); PAC работает без прав
            if self.proxy.needs_admin and not is_admin():
                raise ChimeraError("err.admin.tun")
            return _ok(self.proxy.start())
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('proxy',))
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

    def appearance_state(self, mode=None):
        try:
            result = appearance.state(mode=mode)
            if getattr(self, "_native_theme_changed", None):
                self._native_theme_changed(result["styles"]["--background"])
            return _ok(result)
        except Exception as e:
            return _err(e)

    def appearance_preview(self, patch, mode=None):
        try:
            return _ok(appearance.preview(appconfig.load(), patch, mode))
        except Exception as e:
            return _err(e)

    @_auto_snapshot(("config",))
    def appearance_apply(self, patch, mode=None):
        try:
            config = appearance.merged(appconfig.load(), patch)
            result = appearance.preview(appconfig.load(), patch, mode)
            appconfig.restore_values(config)
            if getattr(self, "push", None):
                self._push("appearanceChanged", result)
            return _ok(result)
        except Exception as e:
            return _err(e)

    def appearance_refresh(self):
        return _ok({**appearance.refresh_catalog(), "state": appearance.state()})

    def config_read(self):
        try:
            return _ok(appconfig.load())
        except Exception as e:
            return _err(e)

    @_auto_snapshot(('config',))
    def config_set(self, key, value):
        try:
            config = appconfig.set_value(key, value)
            if key == "lang" and getattr(self, "push", None):
                self._push("langChanged", i18n.state())
            if key in ("theme", "appearance", "appearance_custom") and getattr(self, "push", None):
                self._push("appearanceChanged", appearance.state())
            return _ok(config)
        except Exception as e:
            return _err(e)

    # --- язык (modules/i18n.py) ------------------------------------------------

    def lang_get(self):
        """Язык программы: что выбрано в настройках (auto | ru | en), что из этого получилось
        сейчас и какой язык у системы."""
        try:
            return _ok(i18n.state())
        except Exception as e:
            return _err(e)

    def i18n_get(self, lang=None):
        """Каталог текстов языка целиком (поверх английского запасного) и правила множественных
        форм: окно собирает текст само по кодам и параметрам. Без языка — текущий."""
        try:
            return _ok(i18n.frontend_payload(lang))
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
                raise ChimeraError("err.admin.autostart")
            # тот же вид, что у autostart_get: фронт кладёт ответ в своё состояние целиком
            return _ok({"enabled": autostart.set_enabled(bool(value)), "supported": autostart.is_supported()})
        except Exception as e:
            return _err(e)
