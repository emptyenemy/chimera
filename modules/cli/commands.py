"""Исполнение команд chimera: общий путь по таблице (registry) и обработчики особых случаев.

Общий путь: аргументы → вызов метода Api через канал управления → данные. Обработчики нужны
там, где команда составная (status, hosts assign), работает без запущенной Chimera (lists,
config, check, logs) или не сводится к одному методу (start, stop, service, path).
"""

import concurrent.futures
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

from modules import control, paths
from modules.cli import client as cl
from modules.cli import pathenv
from modules.cli.client import CliError, Usage
from modules.cli.registry import READ

CHANGES_LOG = paths.data_path("changes.log")
LOG_FILES = {"winws": paths.log_path("winws.log"), "proxy": paths.log_path("proxy.log"),
             "tg": paths.log_path("tgproxy.log")}

WAIT_START = 90.0     # сколько ждём, пока запущенная программа поднимет канал (в т. ч. запрос UAC)
WAIT_STOP = 20.0      # сколько ждём, пока закрывающаяся программа исчезнет
WAIT_RESTART = 60.0   # сколько ждём новую копию после перезапуска
LOG_TAIL_DEFAULT = 40


@dataclass
class Result:
    data: object = None
    lines: list | None = None      # человекочитаемый вывод; None — построить из data
    exit_code: int = 0


@dataclass
class Ctx:
    json: bool = False
    reveal: bool = False
    _client: cl.Client | None = field(default=None, repr=False)

    def client(self) -> cl.Client:
        if self._client is None:
            self._client = cl.connect()
        return self._client

    def call(self, method: str, *args, reveal: bool | None = None):
        return self.client().api(method, *args, reveal=self.reveal if reveal is None else reveal)

    def running(self) -> bool:
        return cl.discover() is not None

    def call_or_local(self, method: str, args: tuple, local):
        """Через приложение, если оно запущено, иначе локальная функция (для offline-команд)."""
        c = cl.discover()
        if c is not None:
            return c.api(method, *args, reveal=self.reveal)
        return local()


# --- вывод по умолчанию -----------------------------------------------------------------

def _scalar(v) -> str:
    if v is True:
        return "да"
    if v is False:
        return "нет"
    if v is None:
        return "—"
    return str(v)


def render(data, indent: int = 0) -> list[str]:
    pad = "  " * indent
    if data is None or data == {} or data == []:
        return []
    if isinstance(data, dict):
        out = []
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out += render(v, indent + 1)
            else:
                out.append(f"{pad}{k}: {_scalar(v) if not isinstance(v, (dict, list)) else '—'}")
        return out
    if isinstance(data, list):
        if all(not isinstance(x, (dict, list)) for x in data):
            return [pad + ", ".join(_scalar(x) for x in data)]
        out = []
        for item in data:
            sub = render(item, indent + 1)
            if sub:
                out.append(f"{pad}- " + sub[0].lstrip())
                out += sub[1:]
            else:
                out.append(f"{pad}- —")
        return out
    return [pad + _scalar(data)]


# --- журнал изменений ----------------------------------------------------------------------

def loggable(act, argv: list[str]) -> str:
    """Команда для журнала: без значений, которые нельзя светить (ссылка прокси, секрет)."""
    words = list(argv)
    if act.command == "proxy link":
        words = [w if w.startswith("--") or i < 2 else "***" for i, w in enumerate(words)]
    if act.command == "tg config":
        for i, w in enumerate(words[:-1]):
            if w == "--secret":
                words[i + 1] = "***"
    if act.command == "tg advanced":
        words = [w.split("=", 1)[0] + "=***" if "=" in w else w for w in words]
    return " ".join(words)


def record_change(act, argv: list[str], ok: bool) -> None:
    if act.level == READ:
        return
    if act.group == "service" and (len(argv) < 2 or argv[1] in ("status", "run")):
        return  # `service run` зовёт планировщик при старте системы: это не правка пользователя
    try:
        with open(CHANGES_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\tcli\t{loggable(act, argv)}\t{'ok' if ok else 'error'}\n")
    except OSError:
        pass  # журнал вспомогательный: не мешаем команде


# --- общий путь -----------------------------------------------------------------------------

def arg_values(act, ns: dict) -> list:
    values = []
    for i, arg in enumerate(act.args):
        v = ns.get(f"a{i}")
        if v is None:
            v = arg.default
        values.append(v)
    return values


def execute(ctx: Ctx, act, ns: dict) -> Result:
    if act.handler:
        return HANDLERS[act.handler](ctx, act, ns)
    return Result(ctx.call(act.method, *act.fixed, *arg_values(act, ns)))


# --- приложение ------------------------------------------------------------------------------

def _state(ctx, method):
    try:
        return ctx.call(method)
    except CliError as e:
        if e.exit_code == 3:  # нет связи или программа старая — это общий отказ, а не ошибка одного модуля
            raise
        return {"error": e.message}


def h_status(ctx, act, ns):
    data = {"app": _state(ctx, "app_info"), "winws": _state(ctx, "winws_state"),
            "proxy": _state(ctx, "proxy_state"), "tg": _state(ctx, "tg_state"),
            "hosts": _state(ctx, "hosts_state")}
    data["winws"] = {k: v for k, v in data["winws"].items() if k != "strategies"}
    app, w, p, t, h = (data[k] for k in ("app", "winws", "proxy", "tg", "hosts"))

    def on(x):
        return "работает" if x.get("running") else "остановлен"

    lines = [f"Chimera {app.get('version', '?')}, права администратора: {_scalar(app.get('admin'))}",
             f"Обход DPI (winws): {on(w)}" + (f", стратегия {w.get('current')}" if w.get("current") else ""),
             f"Прокси: {on(p)}" + (f", режим {p.get('mode')}" if p.get("mode") else ""),
             f"Telegram-прокси: {on(t)}",
             f"hosts: {'применены' if h.get('applied') else 'не применены'}"
             + (f", записей {h.get('count')}" if h.get("count") is not None else "")]
    for name, st in (("winws", w), ("proxy", p), ("tg", t)):
        if st.get("error"):
            lines.append(f"  ошибка {name}: {st['error']}")
    return Result(data, lines)


def h_version(ctx, act, ns):
    from modules.version import VERSION
    return Result({"version": VERSION, "protocol": control.PROTOCOL},
                  [f"Chimera {VERSION} (протокол командной строки {control.PROTOCOL})"])


def launch_app() -> None:
    """Запускает Chimera в трее, отдельным процессом."""
    cmd = control.relaunch_command() + ["--tray"]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, creationflags=flags, close_fds=True)


def _wait(cond, timeout: float, step: float = 0.3) -> bool:
    end = time.monotonic() + timeout
    while True:
        if cond():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(step)


def h_start(ctx, act, ns):
    if cl.discover() is not None:
        return Result({"running": True, "started": False}, ["Chimera уже запущена."])
    launch_app()
    if not _wait(lambda: cl.discover() is not None, WAIT_START, 0.5):
        raise CliError("Не удалось дождаться запуска Chimera. Если появился запрос прав администратора, "
                       "подтвердите его и повторите `chimera start`.", "start_failed", 3)
    return Result({"running": True, "started": True}, ["Chimera запущена."])


def h_stop(ctx, act, ns):
    c = cl.discover()
    if c is None:
        return Result({"running": False}, ["Chimera не запущена."])
    c.action("quit")
    if not _wait(lambda: cl.discover() is None, WAIT_STOP):
        raise CliError("Chimera не закрылась за отведённое время.", "stop_timeout", 1)
    return Result({"running": False}, ["Chimera закрыта."])


def h_restart(ctx, act, ns):
    c = ctx.client()
    c.action("restart")
    if not _wait(lambda: cl.discover() is None, WAIT_STOP):
        raise CliError("Chimera не закрылась для перезапуска.", "stop_timeout", 1)
    if WAIT_RESTART and not _wait(lambda: cl.discover() is not None, WAIT_RESTART, 0.5):
        raise CliError("Chimera не поднялась после перезапуска. Запустите её командой `chimera start`.",
                       "start_failed", 3)
    return Result({"running": True, "restarted": True}, ["Chimera перезапущена."])


def h_sources_check(ctx, act, ns):
    name = ns.get("a0")
    return Result(ctx.call("upstream_check_one", name) if name else ctx.call("upstream_check_updates"))


# --- настройки ---------------------------------------------------------------------------------

def _parse_value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def h_config_get(ctx, act, ns):
    from modules import appconfig
    cfg = ctx.call_or_local("config_read", (), appconfig.load)
    key = ns.get("a0")
    if key is None:
        return Result(cfg)
    if key not in cfg:
        raise CliError(f"Нет настройки {key!r}. Доступные: {', '.join(cfg)}.", "not_found", 1)
    return Result({"key": key, "value": cfg[key]}, [_scalar(cfg[key])])


def h_config_set(ctx, act, ns):
    from modules import appconfig
    key, value = ns["a0"], ns["a1"]
    if cl.discover() is None:
        if key not in control.CONFIG_KEYS_WRITABLE:
            raise CliError(f"Настройку {key!r} через командную строку менять нельзя.", "forbidden", 1)
        return Result(appconfig.set_value(key, value))
    return Result(ctx.call("config_set", key, value))


# --- обход, Telegram, hosts, DNS ----------------------------------------------------------------

def h_winws_strategies(ctx, act, ns):
    items = ctx.call("winws_state").get("strategies") or []
    return Result(items, [f"{s.get('id')} — {s.get('name', '')}" for s in items] or ["Стратегий нет."])


def h_winws_start(ctx, act, ns):
    sid = ns.get("a0") or ctx.call("winws_state").get("last_strategy")
    if not sid:
        raise CliError("Стратегия не выбрана и раньше не запускалась. Список: chimera winws strategies.",
                       "not_found", 1)
    return Result(ctx.call("winws_start", sid), [f"Стратегия {sid} запущена."])


def h_proxy_link(ctx, act, ns):
    link, clear = ns.get("a0"), ns.get("a1")
    if clear:
        link = ""
    elif link == "-":
        link = sys.stdin.read().strip()
    elif link is None:
        raise Usage("Укажите ссылку (или `-` для чтения из stdin), либо --clear.")
    return Result(ctx.call("proxy_set_link", link), ["Ссылка прокси удалена." if not link else "Ссылка прокси сохранена."])


def h_tg_link(ctx, act, ns):
    link = (ctx.call("tg_state") or {}).get("link")
    if not link:
        raise CliError("Ссылка недоступна: ядро Telegram-прокси не загрузилось.", "not_found", 1)
    lines = [link]
    if not ctx.reveal:
        lines.append("Секрет скрыт. Полная ссылка: chimera tg link --show-secrets")
    return Result({"link": link}, lines)


def h_tg_config(ctx, act, ns):
    cur = ctx.call("tg_state", reveal=True)
    host, port, secret, auto = ns.get("a0"), ns.get("a1"), ns.get("a2"), ns.get("a3")
    return Result(ctx.call("tg_set_config",
                           cur.get("host") if host is None else host,
                           cur.get("port") if port is None else port,
                           cur.get("secret") if secret is None else secret,
                           bool(cur.get("autostart")) if auto is None else auto))


def _kv(items: list[str]) -> dict:
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise Usage(f"Нужно ключ=значение, получено {item!r}.")
        out[key.strip()] = _parse_value(value)
    return out


_TG_LIST_KEYS = ("cfproxy_user_domains", "cfproxy_worker_domains")


def h_tg_advanced(ctx, act, ns):
    opts = _kv(ns["a0"])
    for k in _TG_LIST_KEYS:
        if isinstance(opts.get(k), str):
            opts[k] = [x for x in opts[k].split(",") if x.strip()]
    return Result(ctx.call("tg_set_advanced", opts))


def h_hosts_assign(ctx, act, ns):
    given = {}
    for item in ns.get("a0") or []:
        prov, sep, names = item.partition("=")
        if not sep or not prov:
            raise Usage(f"Нужно провайдер=список,список, получено {item!r}.")
        given[prov.strip()] = [n.strip() for n in names.split(",") if n.strip()]
    if ns.get("a1"):
        mapping = given
    else:
        mapping = {**(ctx.call("hosts_state").get("assignments") or {}), **given}
    return Result(ctx.call("hosts_set_assignments", {k: v for k, v in mapping.items() if v}))


def h_hosts_background(ctx, act, ns):
    opts = _kv(ns.get("a0") or [])
    if not opts:
        return Result(ctx.call("hosts_state").get("background"))
    return Result(ctx.call("hosts_set_background", opts))


def h_dns_ping(ctx, act, ns):
    pid = ns.get("a0")
    return Result(ctx.call("dns_ping_one", pid) if pid else ctx.call("dns_ping"))


def h_dns_probe_config(ctx, act, ns):
    bypass, ad = ns.get("a0"), ns.get("a1")
    if bypass is None and ad is None:
        return Result(ctx.call("dns_probe_config"))
    cur = ctx.call("dns_probe_config")
    return Result(ctx.call("dns_set_probe_config", cur.get("bypass") if bypass is None else bypass,
                           cur.get("ad") if ad is None else ad))


# --- списки -----------------------------------------------------------------------------------------

def _domains():
    from modules import domains
    return domains


def _read_list(ctx, name: str) -> str:
    return ctx.call_or_local("lists_read", (name,), lambda: _domains().read_raw(name))


def _list_exists(ctx, name: str) -> bool:
    try:
        _read_list(ctx, name)
        return True
    except (CliError, FileNotFoundError):
        return False


def _save_list(ctx, name: str, text: str):
    return ctx.call_or_local("lists_save", (name, text), lambda: _domains().save_raw(name, text))


def _entries(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def h_lists_show(ctx, act, ns):
    name = ns.get("a0")
    if name is None:
        info = ctx.call_or_local("lists_all", (), lambda: _domains().list_info())
        rows = [f"{i['name']}: {i['count']}" for i in info]
        return Result(info, rows or ["Списков нет."])
    text = _read_list(ctx, name)
    return Result({"name": name, "domains": _entries(text), "content": text}, _entries(text) or ["Список пуст."])


def h_lists_save(ctx, act, ns):
    name, path = ns["a0"], ns.get("a1")
    text = open(path, encoding="utf-8").read() if path else sys.stdin.read()
    return Result(_save_list(ctx, name, text), [f"Список {name} сохранён."])


def h_lists_create(ctx, act, ns):
    name = ns["a0"]
    return Result(ctx.call_or_local("lists_create", (name,), lambda: _domains().create_list(name)),
                  [f"Список {name} создан."])


def h_lists_delete(ctx, act, ns):
    return Result(ctx.call("lists_delete", ns["a0"]), [f"Список {ns['a0']} удалён."])


def h_lists_rename(ctx, act, ns):
    return Result(ctx.call("lists_rename", ns["a0"], ns["a1"]), [f"Список {ns['a0']} переименован в {ns['a1']}."])


def h_lists_add(ctx, act, ns):
    name, items = ns["a0"], ns["a1"]
    text = _read_list(ctx, name) if _list_exists(ctx, name) else f"# {name}\n"
    have = {e.lower() for e in _entries(text)}
    fresh, seen = [], set(have)
    for d in items:
        if d.lower() not in seen:
            seen.add(d.lower())
            fresh.append(d)
    if fresh:
        _save_list(ctx, name, text.rstrip("\n") + "\n" + "\n".join(fresh) + "\n")
    lines = [f"Добавлено: {len(fresh)}" + (f" (уже были: {len(items) - len(fresh)})" if len(fresh) != len(items) else "")]
    return Result({"name": name, "added": fresh, "skipped": [d for d in items if d not in fresh]}, lines)


def h_lists_remove(ctx, act, ns):
    name, items = ns["a0"], ns["a1"]
    text = _read_list(ctx, name)
    drop = {d.lower() for d in items}
    kept, removed = [], []
    for line in text.splitlines():
        (removed if line.strip().lower() in drop else kept).append(line.strip() if line.strip().lower() in drop else line)
    if removed:
        _save_list(ctx, name, "\n".join(kept).rstrip("\n") + "\n")
    return Result({"name": name, "removed": removed}, [f"Удалено: {len(removed)}"])


# --- проверки -----------------------------------------------------------------------------------------

def _check_one(ctx, domain: str, only: str | None) -> dict:
    out = {"domain": domain}
    if only != "registry":
        try:
            out["local"] = ctx.call_or_local("block_check_one", (domain,), lambda: _local_check(domain))
        except CliError as e:
            out["local"] = {"error": e.message}
    if only != "local":
        try:
            out["registry"] = ctx.call_or_local("chebur_check_one", (domain,), lambda: _registry_check(domain))
        except CliError as e:
            out["registry"] = {"error": e.message}
    return out


def _local_check(domain):
    from modules import blockcheck
    return blockcheck.check(domain, socks_addr=None)


def _registry_check(domain):
    from modules import cheburcheck
    return cheburcheck.check(domain)


def h_check_site(ctx, act, ns):
    return Result(_check_one(ctx, ns["a0"], ns.get("a1")))


def h_check_list(ctx, act, ns):
    name, only = ns["a0"], ns.get("a1")
    entries = _entries(_read_list(ctx, name))
    if not entries:
        raise CliError(f"В списке {name} нет доменов.", "not_found", 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda d: _check_one(ctx, d, only), entries))
    return Result({"list": name, "results": results}, [f"{r['domain']}: {_short(r)}" for r in results])


def _short(row: dict) -> str:
    parts = []
    for key in ("local", "registry"):
        v = row.get(key)
        if isinstance(v, dict):
            parts.append(f"{key}={v.get('verdict', v.get('blocked', v.get('error', '?')))}")
    return ", ".join(parts)


# --- логи, служба, PATH -----------------------------------------------------------------------------------

def h_logs(ctx, act, ns):
    module, tail = ns["a0"], ns.get("a1") or LOG_TAIL_DEFAULT
    path = LOG_FILES[module]
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    except OSError:
        lines = []
    return Result({"module": module, "file": str(path), "lines": lines}, lines or ["Лог пуст."])


def h_service(ctx, act, ns):
    from modules import service
    rc = service.cli([ns["a0"], *(ns.get("a1") or [])])
    return Result({"command": ns["a0"]}, [], exit_code=rc or 0)


def h_docs(ctx, act, ns):
    from modules.cli import docs
    topic = ns.get("a0")
    if topic is None:
        return Result(docs.all_data(), docs.index_text().splitlines())
    return Result(docs.topic_data(topic), docs.topic_text(topic).splitlines())


def h_agent_info(ctx, act, ns):
    from modules.cli import docs
    return Result(docs.agent_info(), docs.agent_info_text().splitlines())


def h_path_show(ctx, act, ns):
    d = pathenv.app_dir()
    inside = pathenv.contains(d)
    lines = [f"Папка программы: {d}", "В PATH: " + ("да" if inside else "нет")]
    if not paths.IS_FROZEN:
        lines.append("Запуск из исходников: команда `chimera` появится только у собранной программы.")
    return Result({"dir": str(d), "in_path": inside, "frozen": bool(paths.IS_FROZEN)}, lines)


def h_path_add(ctx, act, ns):
    d = pathenv.app_dir()
    changed = pathenv.add(d)
    return Result({"dir": str(d), "changed": changed},
                  [f"Добавлено в PATH: {d}. Откройте новый терминал." if changed else "Папка уже в PATH."])


def h_path_remove(ctx, act, ns):
    d = pathenv.app_dir()
    changed = pathenv.remove(d)
    return Result({"dir": str(d), "changed": changed},
                  [f"Убрано из PATH: {d}." if changed else "Папки не было в PATH."])


def _sections(text):
    return [x.strip() for x in text.split(",") if x.strip()] if text else None


def _read_arg(path):
    return sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()


def h_doctor(ctx, act, ns):
    if ns.get("a0"):
        text = ctx.call("doctor_report", True)
        return Result({"report": text}, text.splitlines())
    res = ctx.call("doctor_run")
    icons = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
    lines = [f"[{icons.get(c['status'], c['status'])}] {c['title']}: {c['message']}"
             + (f"\n       {c['hint']}" if c["status"] != "ok" and c.get("hint") else "") for c in res["checks"]]
    s = res["summary"]
    lines.append(f"Итого: ok {s['ok']}, замечаний {s['warn']}, проблем {s['fail']}.")
    return Result(res, lines, exit_code=1 if s["fail"] else 0)


def h_config_export(ctx, act, ns):
    text = ctx.call("config_export", _sections(ns.get("a0")))
    path = ns.get("a1")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return Result({"file": path}, [f"Конфиг записан в {path}."])
    return Result({"config": text}, text.splitlines())


def _preview_lines(pv):
    if not pv.get("ok"):
        return [pv.get("error") or "Конфиг не подходит."]
    out = []
    for s in pv["sections"]:
        mark = " (зависит от провайдера)" if s.get("provider_dependent") else ""
        out.append(f"{s['title']}{mark}:")
        out += [f"  {c}" for c in s["changes"]]
        out += [f"  ! {c}" for c in s["confirm"]]
        out += [f"  пропущено: {c}" for c in s["skipped"]]
    if pv.get("needs_confirm"):
        out.append("Есть пункты, требующие подтверждения (!): применяйте с --confirm, только если доверяете автору.")
    return out


def h_config_import_preview(ctx, act, ns):
    pv = ctx.call("config_import_preview", _read_arg(ns["a0"]))
    return Result(pv, _preview_lines(pv), exit_code=0 if pv.get("ok") else 1)


def h_config_import(ctx, act, ns):
    text = _read_arg(ns["a0"])
    sections = _sections(ns.get("a1"))
    if sections is None:
        pv = ctx.call("config_import_preview", text)
        if not pv.get("ok"):
            return Result(pv, _preview_lines(pv), exit_code=1)
        sections = [s["id"] for s in pv["sections"] if not s.get("provider_dependent")]
    res = ctx.call("config_import_apply", text, sections, bool(ns.get("a2")))
    lines = [f"{sid}: {x}" for sid, items in res["applied"].items() for x in items]
    lines += [f"пропущено, {sid}: {x}" for sid, items in res["skipped"].items() for x in items]
    lines += [f"ошибка: {e}" for e in res["errors"]]
    if res.get("backup"):
        lines.append(f"Прежние файлы: {res['backup']}")
    return Result(res, lines or ["Нечего применять."], exit_code=1 if res["errors"] else 0)


HANDLERS = {
    "status": h_status, "version": h_version, "start": h_start, "stop": h_stop, "restart": h_restart,
    "sources_check": h_sources_check, "config_get": h_config_get, "config_set": h_config_set,
    "winws_strategies": h_winws_strategies, "winws_start": h_winws_start, "proxy_link": h_proxy_link, "tg_link": h_tg_link,
    "tg_config": h_tg_config, "tg_advanced": h_tg_advanced, "hosts_assign": h_hosts_assign,
    "hosts_background": h_hosts_background, "dns_ping": h_dns_ping, "dns_probe_config": h_dns_probe_config,
    "lists_show": h_lists_show, "lists_save": h_lists_save, "lists_create": h_lists_create,
    "lists_delete": h_lists_delete, "lists_rename": h_lists_rename, "lists_add": h_lists_add,
    "lists_remove": h_lists_remove, "check_site": h_check_site, "check_list": h_check_list,
    "logs": h_logs, "service": h_service, "docs": h_docs, "agent_info": h_agent_info, "path_show": h_path_show, "path_add": h_path_add,
    "path_remove": h_path_remove,
    "doctor": h_doctor, "config_export": h_config_export,
    "config_import_preview": h_config_import_preview, "config_import": h_config_import,
}
