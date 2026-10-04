"""Исполнение команд chimera: общий путь по таблице (registry) и обработчики особых случаев.

Общий путь: аргументы → вызов метода Api через канал управления → данные. Обработчики нужны
там, где команда составная (status, hosts assign), работает без запущенной Chimera (lists,
config, check, logs) или не сводится к одному методу (start, stop, service, path).
"""

from modules.i18n import t as _tr

import concurrent.futures
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field

from modules import changelog, configbackups, control, errors, i18n, paths
from modules.cli import client as cl
from modules.cli import pathenv
from modules.cli.client import CliError, Usage
from modules.cli.registry import READ
from modules.errors import ChimeraError
from modules.i18n import t

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
        return configbackups.offline_change(method, args, local)


# --- вывод по умолчанию -----------------------------------------------------------------

def _scalar(v) -> str:
    if v is True:
        return t("cli.val.yes")
    if v is False:
        return t("cli.val.no")
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
        for i, word in enumerate(words):
            flag, equal, _value = word.partition('=')
            if flag.startswith('--') and len(flag) > 2 and '--secret'.startswith(flag):
                if equal:
                    words[i] = flag + '=***'
                elif i + 1 < len(words):
                    words[i + 1] = '***'
    if act.command == "tg advanced":
        words = [w.split("=", 1)[0] + "=***" if "=" in w else w for w in words]
    return " ".join(words)


def record_change(act, argv: list[str], ok: bool) -> None:
    if act.level == READ or act.group == "tui":   # tui — интерактивная оболочка: её действия пишет сама (tui/remote.py)
        return
    if act.group == "service" and (len(argv) < 2 or argv[1] in ("status", "run")):
        return  # `service run` зовёт планировщик при старте системы: это не правка пользователя
    changelog.record("cli", loggable(act, argv), ok, CHANGES_LOG)


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


def h_explain(ctx, act, ns):
    from modules import routeexplain
    try:
        target, _addr = routeexplain.normalize_target(ns['a0'])
        app = routeexplain.normalize_app(ns.get('a1'))
    except ChimeraError as e:
        raise Usage.of(e.code, **e.params) from None
    report = ctx.call('route_explain', target, app)
    return Result(report, routeexplain.render(report))


def h_status(ctx, act, ns):
    data = {"app": _state(ctx, "app_info"), "winws": _state(ctx, "winws_state"),
            "proxy": _state(ctx, "proxy_state"), "tg": _state(ctx, "tg_state"),
            "hosts": _state(ctx, "hosts_state")}
    data["winws"] = {k: v for k, v in data["winws"].items() if k != "strategies"}
    app, w, p, tg, h = (data[k] for k in ("app", "winws", "proxy", "tg", "hosts"))

    def on(x):
        return t("cli.status.running") if x.get("running") else t("cli.status.stopped")

    lines = [t("cli.status.app", version=app.get("version", "?"), admin=_scalar(app.get("admin"))),
             t("cli.status.winws", state=on(w)) + (t("cli.status.strategy", strategy=w.get("current")) if w.get("current") else ""),
             t("cli.status.proxy", state=on(p)) + (t("cli.status.mode", mode=p.get("mode")) if p.get("mode") else ""),
             t("cli.status.tg", state=on(tg)),
             t("cli.status.hosts_on" if h.get("applied") else "cli.status.hosts_off")
             + (t("cli.status.hosts_count", count=h.get("count")) if h.get("count") is not None else "")]
    for name, st in (("winws", w), ("proxy", p), ("tg", tg)):
        if st.get("error"):
            lines.append(t("cli.status.error", name=name, error=st["error"]))
    return Result(data, lines)


def h_version(ctx, act, ns):
    from modules.version import VERSION
    return Result({"version": VERSION, "protocol": control.PROTOCOL},
                  [t("cli.version", version=VERSION, protocol=control.PROTOCOL)])


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
        return Result({"running": True, "started": False}, [t("cli.msg.already_running")])
    launch_app()
    if not _wait(lambda: cl.discover() is not None, WAIT_START, 0.5):
        raise CliError.of("cli.err.start_wait", "start_failed", 3)
    return Result({"running": True, "started": True}, [t("cli.msg.started")])


def h_tui(ctx, act, ns):
    if ctx.json:
        raise Usage(_tr('err.cli.commands.chimera_tui_does_not_support_json_output_it_is_i'))
    from tui import launch
    return Result(None, [], exit_code=launch.run(simple=bool(ns.get("a0"))))


def h_stop(ctx, act, ns):
    c = cl.discover()
    if c is None:
        return Result({"running": False}, [t("cli.msg.not_running")])
    c.action("quit")
    if not _wait(lambda: cl.discover() is None, WAIT_STOP):
        raise CliError.of("cli.err.stop_timeout", "stop_timeout", 1)
    return Result({"running": False}, [t("cli.msg.stopped")])


def h_restart(ctx, act, ns):
    c = ctx.client()
    c.action("restart")
    if not _wait(lambda: cl.discover() is None, WAIT_STOP):
        raise CliError.of("cli.err.restart_stop_timeout", "stop_timeout", 1)
    if WAIT_RESTART and not _wait(lambda: cl.discover() is not None, WAIT_RESTART, 0.5):
        raise CliError.of("cli.err.restart_start_wait", "start_failed", 3)
    return Result({"running": True, "restarted": True}, [t("cli.msg.restarted")])


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
        raise CliError.of("cli.err.config_missing", "not_found", 1, key=repr(key), options=", ".join(cfg))
    return Result({"key": key, "value": cfg[key]}, [_scalar(cfg[key])])


def h_config_set(ctx, act, ns):
    from modules import appconfig
    key, value = ns["a0"], ns["a1"]
    if not ctx.running():
        if key not in control.CONFIG_KEYS_WRITABLE:
            raise CliError.of("cli.err.config_forbidden", "forbidden", 1, key=repr(key))
        try:
            return Result(configbackups.offline_change("config_set", (key, value), lambda: appconfig.set_value(key, value)))
        except ChimeraError as e:
            raise CliError(e.message(), "invalid", 1, e.code, e.params) from e
    return Result(ctx.call("config_set", key, value))


# --- язык -------------------------------------------------------------------------------------

def h_lang_show(ctx, act, ns):
    from modules import i18n
    data = ctx.call_or_local("lang_get", (), i18n.state)
    return Result(data, [t("cli.lang.show", setting=data["setting"], lang=data["lang"], system=data["system"])])


def h_lang_set(ctx, act, ns):
    res = h_config_set(ctx, act, {"a0": "lang", "a1": ns["a0"]})
    return Result(res.data, [t("cli.lang.set", setting=ns["a0"])])


def h_lang_catalog(ctx, act, ns):
    from modules import i18n
    lang = ns.get("a0")
    data = ctx.call_or_local("i18n_get", (lang,), lambda: i18n.frontend_payload(lang))
    return Result(data, [t("cli.lang.catalog", lang=data["lang"], count=len(data["catalog"]))])


# --- обход, Telegram, hosts, DNS ----------------------------------------------------------------

def h_winws_strategies(ctx, act, ns):
    items = ctx.call("winws_state").get("strategies") or []
    return Result(items, [f"{s.get('id')} — {s.get('name', '')}" for s in items] or [t("cli.winws.none")])


def h_winws_start(ctx, act, ns):
    sid = ns.get("a0") or ctx.call("winws_state").get("last_strategy")
    if not sid:
        raise CliError.of("cli.err.no_strategy", "not_found", 1)
    return Result(ctx.call("winws_start", sid), [t("cli.winws.started", strategy=sid)])


def h_proxy_link(ctx, act, ns):
    link, clear = ns.get("a0"), ns.get("a1")
    if clear:
        link = ""
    elif link == "-":
        link = sys.stdin.read().strip()
    elif link is None:
        raise Usage.of("cli.usage.link_needed")
    return Result(ctx.call("proxy_set_link", link), [t("cli.proxy.link_cleared" if not link else "cli.proxy.link_saved")])


def h_tg_link(ctx, act, ns):
    link = (ctx.call("tg_state") or {}).get("link")
    if not link:
        raise CliError.of("cli.err.tg_no_link", "not_found", 1)
    return Result({"link": link}, [link])


def h_tg_config(ctx, act, ns):
    cur = ctx.call("tg_state")
    host, port, secret, auto = ns.get("a0"), ns.get("a1"), ns.get("a2"), ns.get("a3")
    return Result(ctx.call("tg_set_config",
                           cur.get("host") if host is None else host,
                           cur.get("port") if port is None else port,
                           secret,
                           bool(cur.get("autostart")) if auto is None else auto))


def _kv(items: list[str]) -> dict:
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise Usage.of("cli.usage.need_kv", item=repr(item))
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
            raise Usage.of("cli.usage.need_assign", item=repr(item))
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


def _read_list_for_add(ctx, name: str) -> str:
    try:
        return _read_list(ctx, name)
    except FileNotFoundError:
        return f'# {name}\n'
    except CliError as error:
        if error.code == 'not_found' or error.key in (
                'err.domains.list_was_not_found', 'err.domains.domain_list_was_not_found_in'):
            return f'# {name}\n'
        raise


def _save_list(ctx, name: str, text: str):
    return ctx.call_or_local("lists_save", (name, text), lambda: _domains().save_raw(name, text))


def _entries(text: str) -> list[str]:
    return [entry for line in text.splitlines() if (entry := line.split('#', 1)[0].strip())]


def h_lists_show(ctx, act, ns):
    name = ns.get("a0")
    if name is None:
        info = ctx.call_or_local("lists_all", (), lambda: _domains().list_info())
        rows = [f"{i['name']}: {i['count']}" for i in info]
        return Result(info, rows or [t("cli.lists.none")])
    text = _read_list(ctx, name)
    return Result({"name": name, "domains": _entries(text), "content": text}, _entries(text) or [t("cli.lists.empty")])


def _saved_list_result(data, lines):
    apply_errors = data.get('apply_errors') or []
    lines += [t('cli.lists.apply_error', module=error['module'], error=error['error']) for error in apply_errors]
    return Result(data, lines, exit_code=1 if apply_errors else 0)


def h_lists_save(ctx, act, ns):
    name, path = ns["a0"], ns.get("a1")
    text = open(path, encoding="utf-8").read() if path else sys.stdin.read()
    return _saved_list_result(_save_list(ctx, name, text), [t("cli.lists.saved", name=name)])


def h_lists_create(ctx, act, ns):
    name = ns["a0"]
    return Result(ctx.call_or_local("lists_create", (name,), lambda: _domains().create_list(name)),
                  [t("cli.lists.created", name=name)])


def h_lists_delete(ctx, act, ns):
    return Result(ctx.call("lists_delete", ns["a0"]), [t("cli.lists.deleted", name=ns["a0"])])


def h_lists_rename(ctx, act, ns):
    return Result(ctx.call("lists_rename", ns["a0"], ns["a1"]), [t("cli.lists.renamed", old=ns["a0"], new=ns["a1"])])


def h_lists_add(ctx, act, ns):
    name, items = ns["a0"], ns["a1"]
    text = _read_list_for_add(ctx, name)
    have = {e.lower() for e in _entries(text)}
    fresh, seen = [], set(have)
    for d in items:
        if d.lower() not in seen:
            seen.add(d.lower())
            fresh.append(d)
    saved = _save_list(ctx, name, text.rstrip("\n") + "\n" + "\n".join(fresh) + "\n") if fresh else {}
    lines = [t("cli.lists.added", count=len(fresh))
             + (t("cli.lists.added_skipped", count=len(items) - len(fresh)) if len(fresh) != len(items) else "")]
    data = {"name": name, "added": fresh, "skipped": [d for d in items if d not in fresh]}
    if saved.get("apply_errors"):
        data["apply_errors"] = saved["apply_errors"]
    return _saved_list_result(data, lines)


def h_lists_remove(ctx, act, ns):
    name, items = ns["a0"], ns["a1"]
    text = _read_list(ctx, name)
    drop = {d.lower() for d in items}
    kept, removed = [], []
    for line in text.splitlines():
        entry = line.split('#', 1)[0].strip()
        (removed if entry.lower() in drop else kept).append(entry if entry.lower() in drop else line)
    saved = _save_list(ctx, name, "\n".join(kept).rstrip("\n") + "\n") if removed else {}
    data = {"name": name, "removed": removed}
    if saved.get("apply_errors"):
        data["apply_errors"] = saved["apply_errors"]
    return _saved_list_result(data, [t("cli.lists.removed", count=len(removed))])


def h_lists_validate(ctx, act, ns):
    name = ns.get("a0")
    try:
        results = ctx.call_or_local("lists_validate", (name,), lambda: _domains().validate_lists(name))["lists"]
    except (FileNotFoundError, ValueError) as e:
        raise CliError(str(e), "not_found", 1, "err.raw", {"message": str(e)}) from e
    lines = []
    for r in results:
        lines.append(t("cli.lists.check_line", name=r["name"],
                       errors=t("cli.lists.no_errors") if r["ok"] else t("cli.lists.n_errors", count=len(r["errors"])),
                       entries=t("cli.lists.n_entries", count=r["entries"]),
                       domains=t("cli.lists.n_domains", count=r["domains"]),
                       networks=t("cli.lists.n_networks", count=r["networks"]),
                       warnings=(", " + t("cli.lists.n_warnings", count=len(r["warnings"]))) if r["warnings"] else ""))
        for kind, items in (("cli.lists.kind_error", r["errors"]), ("cli.lists.kind_warning", r["warnings"])):
            for p in items:
                where = t("cli.lists.at_line", line=p["line"]) if p["line"] else t("cli.lists.at_file")
                lines.append(t("cli.lists.problem", kind=t(kind), where=where, problem=p["problem"])
                             + (f" ({p['entry']})" if p["entry"] else ""))
    bad = sum(1 for r in results if not r["ok"])
    return Result({"lists": results}, lines or [t("cli.lists.none")], exit_code=1 if bad else 0)


def h_lists_apply(ctx, act, ns):
    from modules import service
    name = ns.get("a0")
    if not ctx.running() and service.is_running():
        raise CliError.of("cli.err.service_only", "service_only", 3)
    res = ctx.call("lists_apply", name)
    lines = [t("cli.lists.applied", names=", ".join(res["applied"]) or t("cli.lists.applied_none"))]
    lines.append(t("cli.lists.used_by", modules=", ".join(res["modules"]) if res["modules"] else t("cli.lists.used_by_none")))
    lines += [t("cli.lists.apply_error", module=e["module"], error=e["error"]) for e in res["apply_errors"]]
    return Result(res, lines, exit_code=1 if res["apply_errors"] else 0)


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
        raise CliError.of("cli.err.list_no_domains", "not_found", 1, name=name)
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
    return Result({"module": module, "file": str(path), "lines": lines}, lines or [t("cli.logs.empty")])


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
    lines = [t("cli.path.dir", dir=d), t("cli.path.in_path", value=t("cli.val.yes" if inside else "cli.val.no"))]
    if not paths.IS_FROZEN:
        lines.append(t("cli.path.from_source"))
    return Result({"dir": str(d), "in_path": inside, "frozen": bool(paths.IS_FROZEN)}, lines)


def h_path_add(ctx, act, ns):
    d = pathenv.app_dir()
    changed = pathenv.add(d)
    return Result({"dir": str(d), "changed": changed},
                  [t("cli.path.added", dir=d) if changed else t("cli.path.already")])


def h_path_remove(ctx, act, ns):
    d = pathenv.app_dir()
    changed = pathenv.remove(d)
    return Result({"dir": str(d), "changed": changed},
                  [t("cli.path.removed", dir=d) if changed else t("cli.path.not_there")])


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
    lines.append(t("cli.doctor.summary", ok=s["ok"], warn=s["warn"], fail=s["fail"]))
    return Result(res, lines, exit_code=1 if s["fail"] else 0)


def h_config_export(ctx, act, ns):
    text = ctx.call("config_export", _sections(ns.get("a0")))
    path = ns.get("a1")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return Result({"file": path}, [t("cli.config.written", path=path)])
    return Result({"config": text}, text.splitlines())


def _preview_lines(pv):
    if not pv.get("ok"):
        return [errors.localized(pv) if pv.get("error") else t("cli.config.unfit")]
    out = []
    for s in pv["sections"]:
        mark = t("cli.config.provider_dependent") if s.get("provider_dependent") else ""
        out.append(f"{s['title']}{mark}:")
        out += [f"  {c}" for c in s["changes"]]
        out += [f"  ! {c}" for c in s["confirm"]]
        out += [t("cli.config.skipped_item", item=c) for c in s["skipped"]]
    if pv.get("needs_confirm"):
        out.append(t("cli.config.needs_confirm"))
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
    lines += [t("cli.config.skipped_in", section=sid, item=x) for sid, items in res["skipped"].items() for x in items]
    lines += [t("cli.config.error_item", error=e) for e in res["errors"]]
    if res.get("backup"):
        lines.append(t("cli.config.backup", path=res["backup"]))
    return Result(res, lines or [t("cli.config.nothing")], exit_code=1 if res["errors"] else 0)


def h_config_backup(ctx, act, ns):
    backup = ctx.call("config_backup_create", i18n.current_lang())
    return Result(backup, [t("cli.backup.created", id=backup["id"])])


def h_config_verify(ctx, act, ns):
    reply = ctx.call("config_verify", ns["a0"], i18n.current_lang())
    lines = [f"{check['domain']}: {check['status']}" for check in reply["checks"]]
    if reply["saved"]:
        lines.append(t("cli.verified.saved", id=reply["backup"]["id"]))
    else:
        lines.append(reply["error"])
    return Result(reply, lines, exit_code=0 if reply["saved"] else 1)


def h_config_verified(ctx, act, ns):
    reply = ctx.call("config_verified", i18n.current_lang())
    backup = reply["backup"]
    lines = ([f"{backup['id']}  {backup['checked_at']}",
              ", ".join(c["domain"] for c in backup["checks"])] if backup else
             [reply["error"] or t("cli.verified.empty")])
    return Result(reply, lines, exit_code=1 if reply["error"] else 0)


def h_config_backups(ctx, act, ns):
    backups = ctx.call("config_backups", i18n.current_lang())
    lines = [f"{b['id']}  {b.get('created_at') or '—'}  {', '.join(b['sections'])}" +
             (f"  ! {b['error']}" if not b['valid'] else "") for b in backups]
    return Result(backups, lines or [t("cli.backup.empty")])


def h_config_compare(ctx, act, ns):
    pv = ctx.call("config_backup_compare", ns["a0"], ns["a1"], i18n.current_lang())
    lines = [f"{pv['left_id']} → {pv['right_id']}"] if pv.get("ok") else []
    for section in pv.get("sections", []):
        lines.append(f"{section['title']}:")
        lines.extend(f"  {line}" for line in section["changes"])
    if pv.get("identical"):
        lines.append(t("msg.backup.compare.identical"))
    lines.extend(f"! {line}" for line in pv.get("warnings", []))
    lines.extend(t("cli.config.error_item", error=line) for line in pv.get("errors", []))
    return Result(pv, lines, exit_code=0 if pv.get("ok") else 1)


def h_config_restore_preview(ctx, act, ns):
    pv = ctx.call("config_backup_preview", ns["a0"], i18n.current_lang())
    lines = []
    for section in pv.get("sections", []):
        lines.append(f"{section['title']}:")
        lines.extend(f"  {line}" for line in section["changes"])
    lines.extend(f"! {line}" for line in pv.get("warnings", []))
    lines.extend(t("cli.config.error_item", error=line) for line in pv.get("errors", []))
    if pv.get("requires_admin"):
        lines.append(t("msg.backup.admin_required"))
    return Result(pv, lines or [t("cli.config.nothing")], exit_code=0 if pv.get("ok") else 1)


def h_config_restore(ctx, act, ns):
    res = ctx.call("config_backup_restore", ns["a0"], bool(ns.get("a1")), i18n.current_lang())
    lines = [t("cli.backup.restored", sections=", ".join(res["restored"]))] if res["restored"] else []
    lines.extend(t("cli.config.error_item", error=line) for line in res["errors"])
    lines.extend(t("cli.config.error_item", error=line) for line in res["rollback_errors"])
    if res["rolled_back"]:
        lines.append(t("cli.backup.rolled_back"))
    if res.get("backup"):
        lines.append(t("cli.backup.inverse", id=res["backup"]))
    return Result(res, lines, exit_code=1 if res["errors"] or res["rollback_errors"] else 0)


# --- автонастройка ----------------------------------------------------------------------------------------

FIX_POLL = 1.0
# семейства строк: ключ собирается из значения (причина, фаза, способ...)
FIX_REASON, FIX_PHASE, FIX_VIA, FIX_HINT, FIX_STEP = (
    "cli.fix.reason", "cli.fix.phase", "cli.fix.via", "cli.fix.hint", "cli.fix.step")


def _fix_reason(row) -> str:
    reasons = row.get("reasons") or []
    return ", ".join(t(f"{FIX_REASON}.{r}") for r in reasons) or t("cli.fix.reason.error")


def _fix_session_lines(session) -> list[str]:
    if session is None:
        return [t("cli.fix.none")]
    phase = session.get("phase")
    report = session.get("report") or {}
    lines = [t(f"{FIX_PHASE}.{phase}")]
    if report.get("offline"):
        lines.append(t("cli.fix.offline"))
    for row in report.get("services") or []:
        name, after = row["name"], row.get("after") or {}
        if row.get("skipped"):
            lines.append(t("cli.fix.row.skipped", name=name))
        elif after.get("ok") and row.get("fix"):
            fix = row["fix"]
            lines.append(t("cli.fix.row.fixed", name=name, via=t(f"{FIX_VIA}.{fix['kind']}", id=fix["id"])))
        elif after.get("ok"):
            lines.append(t("cli.fix.row.ok", name=name))
        else:
            lines.append(t("cli.fix.row.broken", name=name, reason=_fix_reason(after),
                           hint=t(f"{FIX_HINT}.{row.get('hint') or 'nothing_helped'}")))
    return lines


def h_fix_run(ctx, act, ns):
    services, smart = arg_values(act, ns)
    state = ctx.call("autotune_start", services or None, "smart" if smart else "fast")
    shown = None
    while (state.get("active") or {}).get("phase") == "running":
        current = state["active"].get("current")
        if not ctx.json and current and current != shown:
            print(t("cli.fix.progress", step=t(f"{FIX_STEP}.{current['step']}"), candidate=current["candidate"],
                    n=current["index"] + 1, total=current["total"]), flush=True)
            shown = current
        time.sleep(FIX_POLL)
        state = ctx.call("autotune_state")
    session = state.get("active") or state.get("last")
    report = (session or {}).get("report") or {}
    broken = [r for r in report.get("services") or [] if not r.get("skipped") and not (r.get("after") or {}).get("ok")]
    done = (session or {}).get("phase") == "done"
    lines = _fix_session_lines(session) + ([t("cli.fix.revert_hint")] if done and report.get("fixes") else [])
    return Result(state, lines, exit_code=0 if done and not broken else 1)


def h_fix_check(ctx, act, ns):
    (services,) = arg_values(act, ns)
    data = ctx.call("autotune_diagnose", services or None)
    lines = [t("cli.fix.offline")] if data.get("offline") else []
    for row in data.get("services") or []:
        if row.get("skipped"):
            lines.append(t("cli.fix.row.skipped", name=row["name"]))
        elif row.get("ok"):
            lines.append(t("cli.fix.row.ok", name=row["name"]))
        else:
            lines.append(t("cli.fix.row.check", name=row["name"], reason=_fix_reason(row),
                           covered=row.get("covered", 0), total=row.get("total", 0)))
    broken = [r for r in data.get("services") or [] if r.get("ok") is False]
    return Result(data, lines, exit_code=1 if broken or data.get("offline") else 0)


# --- стратегии и списки по воздуху -------------------------------------------------------------------

def h_data_check(ctx, act, ns):
    info = ctx.call("data_check")
    if info.get("error"):
        raise CliError.of(info["error"], "unavailable", 1)
    lines = [t("cli.data.current", version=info.get("current") or "—")]
    plan = info.get("plan") or {}
    if not info.get("update"):
        lines.append(t("cli.data.latest"))
    else:
        lines.append(t("cli.data.available", version=info["latest"], add=len(plan.get("add", [])),
                       update=len(plan.get("update", [])), keep=len(plan.get("keep", []))))
        lines += [t("cli.data.kept", path=p) for p in plan.get("keep", [])]
        if not info.get("installable"):
            lines.append(t("cli.data.app_too_old", version=info.get("min_app") or "?"))
    return Result(info, lines)


def h_data_update(ctx, act, ns):
    res = ctx.call("data_update")
    lines = [t("cli.data.installed", version=res["version"], add=len(res["added"]), update=len(res["updated"]),
               keep=len(res["kept"]))]
    lines += [t("cli.data.kept", path=p) for p in res["kept"]]
    if res.get("restarted"):
        lines.append(t("cli.data.restarted"))
    if res.get("restart_error"):
        lines.append(res["restart_error"])
    lines += [t("cli.lists.apply_error", module=e["module"], error=e["error"]) for e in res.get("apply_errors") or []]
    return Result(res, lines, exit_code=1 if res.get("apply_errors") or res.get("restart_error") else 0)


def h_proxy_servers(ctx, act, ns):
    rows = ctx.call("proxy_ping_servers")
    lines = [t("cli.proxy.server_row", n=r["index"], label=r["label"], server=r["server"], protocol=r["protocol"],
               ping=t("cli.proxy.ping_ms", ms=r["ms"]) if r.get("ms") is not None else t("cli.proxy.ping_none"))
             + (" " + t("cli.proxy.current") if r.get("current") else "") for r in rows]
    return Result(rows, lines or [t("cli.proxy.no_servers")])


def h_trial_start(ctx, act, ns):
    kind, target, seconds, domains = arg_values(act, ns)
    checks = [name.strip() for name in domains.split(",")] if domains is not None else None
    return Result(ctx.call("trial_start", kind, target, seconds, checks))


HANDLERS = {
    "trial_start": h_trial_start, "explain": h_explain, "fix_run": h_fix_run, "fix_check": h_fix_check,
    "data_check": h_data_check, "data_update": h_data_update, "proxy_servers": h_proxy_servers,
    "status": h_status, "version": h_version, "start": h_start, "tui": h_tui, "stop": h_stop, "restart": h_restart,
    "sources_check": h_sources_check, "config_get": h_config_get, "config_set": h_config_set,
    "lang_show": h_lang_show, "lang_set": h_lang_set, "lang_catalog": h_lang_catalog,
    "winws_strategies": h_winws_strategies, "winws_start": h_winws_start, "proxy_link": h_proxy_link, "tg_link": h_tg_link,
    "tg_config": h_tg_config, "tg_advanced": h_tg_advanced, "hosts_assign": h_hosts_assign,
    "hosts_background": h_hosts_background, "dns_ping": h_dns_ping, "dns_probe_config": h_dns_probe_config,
    "lists_show": h_lists_show, "lists_save": h_lists_save, "lists_create": h_lists_create,
    "lists_delete": h_lists_delete, "lists_rename": h_lists_rename, "lists_add": h_lists_add,
    "lists_remove": h_lists_remove, "lists_validate": h_lists_validate, "lists_apply": h_lists_apply,
    "check_site": h_check_site, "check_list": h_check_list,
    "logs": h_logs, "service": h_service, "docs": h_docs, "agent_info": h_agent_info, "path_show": h_path_show, "path_add": h_path_add,
    "path_remove": h_path_remove,
    "doctor": h_doctor, "config_export": h_config_export,
    "config_import_preview": h_config_import_preview, "config_import": h_config_import,
    "config_verify": h_config_verify, "config_verified": h_config_verified,
    "config_compare": h_config_compare, "config_backup": h_config_backup, "config_backups": h_config_backups,
    "config_restore_preview": h_config_restore_preview,
    "config_restore": h_config_restore,
}
