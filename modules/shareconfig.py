"""Обмен конфигом: поделиться частью настроек одним файлом (JSON, схема `schema`).

Разделы независимы, и при экспорте, и при импорте каждый включается отдельно:
  • lists    — списки доменов (только на которые ссылаются выбранные разделы, либо заданные);
  • proxy    — режим, выбранные списки, приложения. Ссылки на сервер нет;
  • hosts    — привязки списков к провайдерам и свои «разблокирующие» провайдеры;
  • dns      — свои DNS-провайдеры;
  • telegram — порт и продвинутые опции. Секрета и адреса прослушивания нет;
  • winws    — стратегия, списки, фильтры. Зависит от провайдера, поэтому по умолчанию
               в экспорт не входит и в предпросмотре помечен.

Чужой файл — недоверенные данные: разбор идёт по белому списку полей с проверкой типов,
путей и команд в нём быть не может, неизвестное не применяется, но и не теряется молча
(попадает в отчёт). Всё, что подменяет ответы DNS или ходит через чужие серверы
(провайдеры, домены-ретрансляторы Telegram), применяется только с подтверждением.

Модуль не знает про систему: текущее состояние приходит словарём (snapshot), изменения
делает объект ops (см. ui/api.py: ShareOps), поэтому логика проверяется тестами.
"""

import ipaddress
import json
import re
import shutil
import time
from pathlib import Path

from . import domains, paths, version
from .provider_util import parse_servers, validate_doh, validate_host

SCHEMA = 1
SECTIONS = ("lists", "proxy", "hosts", "dns", "telegram", "winws")
DEFAULT_SECTIONS = ("lists", "proxy", "hosts", "dns", "telegram")
PROVIDER_DEPENDENT = ("winws",)   # настройки обхода DPI зависят от провайдера пользователя
TITLES = {
    "lists": "Списки доменов", "proxy": "Прокси", "hosts": "Hosts", "dns": "DNS-провайдеры",
    "telegram": "Telegram-прокси", "winws": "Обход DPI",
}

MAX_TEXT = 2 * 1024 * 1024        # размер файла целиком
MAX_LISTS = 200
MAX_LIST_LINES = 20000
KEEP_BACKUPS = 10

_MODES = ("pac", "split", "tun")
_IPSET_MODES = ("none", "any", "loaded")
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_LINE_RE = re.compile(r"[A-Za-z0-9._*:/\-\[\]]{1,253}")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_TG_BOOLS = ("disable_secure", "fallback_cfproxy", "proxy_protocol", "force_test_dc")
_TG_DOMAINS = ("cfproxy_user_domains", "cfproxy_worker_domains")
_TG_KEYS = _TG_BOOLS + _TG_DOMAINS + ("fake_tls_domain", "dc_redirects")
_PROVIDER_KEYS = ("id", "name", "servers", "ipv6", "doh", "dot", "filter")


# --- экспорт -------------------------------------------------------------------------------

def _provider_spec(p: dict) -> dict:
    return {k: p.get(k, [] if k in ("servers", "ipv6") else ("" if k != "filter" else False))
            for k in _PROVIDER_KEYS}


def build_export(snapshot: dict, sections, app_version: str, list_names=None) -> dict:
    """Документ для файла. Берёт только белый список полей: секретов и локальных адресов
    (ссылка прокси, секрет и адрес прослушивания Telegram-прокси) в нём нет."""
    chosen = [s for s in SECTIONS if s in set(sections)]
    out = {}

    if "proxy" in chosen:
        p = snapshot.get("proxy") or {}
        out["proxy"] = {"mode": p.get("mode"), "lists": list(p.get("lists") or []), "apps": list(p.get("apps") or [])}
    if "hosts" in chosen:
        h = snapshot.get("hosts") or {}
        out["hosts"] = {"assignments": {k: list(v) for k, v in (h.get("assignments") or {}).items()},
                        "providers": [_provider_spec(p) for p in h.get("providers") or []]}
    if "dns" in chosen:
        out["dns"] = {"providers": [_provider_spec(p) for p in (snapshot.get("dns") or {}).get("providers") or []]}
    if "telegram" in chosen:
        t = snapshot.get("telegram") or {}
        adv = t.get("advanced") or {}
        out["telegram"] = {"port": t.get("port"), "advanced": {k: adv[k] for k in _TG_KEYS if k in adv}}
    if "winws" in chosen:
        w = snapshot.get("winws") or {}
        out["winws"] = {"strategy": w.get("strategy"), "lists": list(w.get("lists") or []),
                        "game": dict(w.get("game") or {}), "ipset": w.get("ipset")}
    if "lists" in chosen:
        have = snapshot.get("lists") or {}
        if list_names is not None:
            wanted = [n for n in list_names if n in have]
        else:
            wanted = _referenced_lists(out)
        out["lists"] = {"items": {n: have[n] for n in wanted if n in have}}

    ordered = {s: out[s] for s in SECTIONS if s in out}
    return {"schema": SCHEMA, "app_version": app_version,
            "min_app_version": app_version if version.parse(app_version) else None, "sections": ordered}


def _referenced_lists(sections: dict) -> list[str]:
    names = []
    for n in (sections.get("proxy") or {}).get("lists", []):
        names.append(n)
    for lst in ((sections.get("hosts") or {}).get("assignments") or {}).values():
        names.extend(lst)
    names.extend((sections.get("winws") or {}).get("lists", []))
    seen, res = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return res


# --- разбор чужого файла ---------------------------------------------------------------------

def _names(value, where, invalid) -> list[str] | None:
    if not isinstance(value, list):
        invalid.append(f"{where}: ожидался список названий")
        return None
    out = []
    for n in value:
        if isinstance(n, str) and domains.NAME_RE.match(n):
            out.append(n)
        else:
            invalid.append(f"{where}: недопустимое имя «{n}»")
    return out


def _clean_list_text(text: str) -> tuple[str, int]:
    out, dropped = [], 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            out.append(_CTRL_RE.sub("", line)[:200])
        elif _LINE_RE.fullmatch(line):
            out.append(line)
        else:
            dropped += 1
    return ("\n".join(out) + "\n") if out else "", dropped


def _entries(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _clean_provider(p, where, invalid):
    if not isinstance(p, dict):
        invalid.append(f"{where}: ожидался объект")
        return None
    name = str(p.get("name") or "").strip()
    if not name or len(name) > 64:
        invalid.append(f"{where}: нет названия")
        return None
    try:
        servers = parse_servers(p.get("servers") or [])
        ipv6 = parse_servers(p.get("ipv6") or [])
        doh = validate_doh(p.get("doh") or "")
        dot = validate_host(p.get("dot") or "")
    except (ValueError, TypeError, AttributeError) as e:
        invalid.append(f"{where} «{name}»: {e}")
        return None
    if not (servers or ipv6 or doh or dot):
        invalid.append(f"{where} «{name}»: нет ни IP-адреса, ни DoH/DoT")
        return None
    pid = p.get("id") if isinstance(p.get("id"), str) and _ID_RE.match(p["id"]) else ""
    return {"id": pid, "name": name, "servers": servers, "ipv6": ipv6, "doh": doh, "dot": dot,
            "filter": bool(p.get("filter"))}


def _unknown(section: dict, allowed) -> list[str]:
    return sorted(k for k in section if k not in allowed)


def _clean_section(sid: str, raw, invalid) -> tuple[dict, list[str]]:
    """(нормализованный раздел, неизвестные поля). raw — объект из файла."""
    if not isinstance(raw, dict):
        invalid.append(f"{sid}: ожидался объект")
        return {}, []
    out, unknown = {}, []

    if sid == "lists":
        unknown = _unknown(raw, ("items",))
        items = raw.get("items")
        clean = {}
        if isinstance(items, dict):
            for name, text in list(items.items())[:MAX_LISTS]:
                if not (isinstance(name, str) and domains.NAME_RE.match(name)):
                    invalid.append(f"список «{name}»: недопустимое имя")
                    continue
                if not isinstance(text, str) or text.count("\n") > MAX_LIST_LINES:
                    invalid.append(f"список «{name}»: неверное или слишком большое содержимое")
                    continue
                cleaned, dropped = _clean_list_text(text)
                if dropped:
                    invalid.append(f"список «{name}»: отброшено строк с недопустимыми символами: {dropped}")
                clean[name] = cleaned
        elif items is not None:
            invalid.append("lists.items: ожидался объект")
        out["items"] = clean

    elif sid == "proxy":
        unknown = _unknown(raw, ("mode", "lists", "apps"))
        if "mode" in raw:
            if raw["mode"] in _MODES:
                out["mode"] = raw["mode"]
            else:
                invalid.append(f"proxy.mode: неизвестный режим «{raw['mode']}»")
        if "lists" in raw:
            names = _names(raw["lists"], "proxy.lists", invalid)
            if names is not None:
                out["lists"] = names
        if "apps" in raw:
            if isinstance(raw["apps"], list):
                apps = []
                for a in raw["apps"]:
                    if (isinstance(a, str) and a.lower().endswith(".exe") and len(a) > 4
                            and not any(c in a for c in '\\/:*?"<>|')):
                        apps.append(a)
                    else:
                        invalid.append(f"proxy.apps: недопустимое имя «{a}»")
                out["apps"] = apps
            else:
                invalid.append("proxy.apps: ожидался список")

    elif sid in ("hosts", "dns"):
        unknown = _unknown(raw, ("assignments", "providers") if sid == "hosts" else ("providers",))
        provs = []
        if isinstance(raw.get("providers"), list):
            for i, p in enumerate(raw["providers"]):
                clean = _clean_provider(p, f"{sid}.providers[{i}]", invalid)
                if clean:
                    provs.append(clean)
        elif "providers" in raw:
            invalid.append(f"{sid}.providers: ожидался список")
        out["providers"] = provs
        if sid == "hosts":
            assign = {}
            if isinstance(raw.get("assignments"), dict):
                for pid, lst in raw["assignments"].items():
                    if not (isinstance(pid, str) and _ID_RE.match(pid)):
                        invalid.append(f"hosts.assignments: недопустимый провайдер «{pid}»")
                        continue
                    names = _names(lst, f"hosts.assignments[{pid}]", invalid)
                    if names:
                        assign[pid] = names
            elif "assignments" in raw:
                invalid.append("hosts.assignments: ожидался объект")
            out["assignments"] = assign

    elif sid == "telegram":
        unknown = _unknown(raw, ("port", "advanced"))
        port = raw.get("port")
        if "port" in raw:
            if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
                out["port"] = port
            else:
                invalid.append(f"telegram.port: недопустимый порт «{port}»")
        adv_raw = raw.get("advanced")
        if isinstance(adv_raw, dict):
            adv = {}
            for k in _unknown(adv_raw, _TG_KEYS):
                unknown.append(f"advanced.{k}")
            for k in _TG_BOOLS:
                if k in adv_raw:
                    if isinstance(adv_raw[k], bool):
                        adv[k] = adv_raw[k]
                    else:
                        invalid.append(f"telegram.advanced.{k}: ожидалось да/нет")
            for k in _TG_DOMAINS:
                if k in adv_raw:
                    v = adv_raw[k]
                    if isinstance(v, list) and all(isinstance(d, str) for d in v):
                        adv[k] = list(v)
                    else:
                        invalid.append(f"telegram.advanced.{k}: ожидался список доменов")
            if "fake_tls_domain" in adv_raw:
                v = adv_raw["fake_tls_domain"]
                if isinstance(v, str):
                    adv["fake_tls_domain"] = v.strip()
                else:
                    invalid.append("telegram.advanced.fake_tls_domain: ожидалась строка")
            if "dc_redirects" in adv_raw:
                v = adv_raw["dc_redirects"]
                ok = isinstance(v, dict)
                clean = {}
                if ok:
                    for dc, ip in v.items():
                        try:
                            ipaddress.ip_address(str(ip))
                            if not (str(dc).isdigit() and 1 <= int(dc) <= 5):
                                raise ValueError
                            clean[str(dc)] = str(ip)
                        except ValueError:
                            invalid.append(f"telegram.advanced.dc_redirects: «{dc}: {ip}» не подходит")
                    adv["dc_redirects"] = clean
                else:
                    invalid.append("telegram.advanced.dc_redirects: ожидался объект")
            out["advanced"] = adv
        elif "advanced" in raw:
            invalid.append("telegram.advanced: ожидался объект")

    elif sid == "winws":
        from .winws import filters
        unknown = _unknown(raw, ("strategy", "lists", "game", "ipset"))
        if "strategy" in raw and raw["strategy"] is not None:
            s = raw["strategy"]
            if isinstance(s, str) and _ID_RE.match(s):
                out["strategy"] = s
            else:
                invalid.append(f"winws.strategy: недопустимое имя «{s}»")
        if "lists" in raw:
            names = _names(raw["lists"], "winws.lists", invalid)
            if names is not None:
                out["lists"] = names
        game = raw.get("game")
        if isinstance(game, dict):
            g = {}
            if game.get("mode") in filters.GAME_MODES:
                g["mode"] = game["mode"]
            elif "mode" in game:
                invalid.append(f"winws.game.mode: недопустимое значение «{game['mode']}»")
            for k in ("tcp", "udp"):
                if k in game:
                    try:
                        g[k] = filters.validate_game_range(game[k])
                    except (ValueError, TypeError) as e:
                        invalid.append(f"winws.game.{k}: {e}")
            out["game"] = g
        elif "game" in raw:
            invalid.append("winws.game: ожидался объект")
        if "ipset" in raw:
            if raw["ipset"] in _IPSET_MODES:
                out["ipset"] = raw["ipset"]
            else:
                invalid.append(f"winws.ipset: недопустимый режим «{raw['ipset']}»")

    return out, unknown


def parse(text: str, current_version: str | None = None) -> dict:
    """Разбор файла. doc — нормализованный документ или None; error — что сказать
    пользователю, если применять нечего."""
    current_version = current_version if current_version is not None else version.VERSION
    res = {"doc": None, "error": None, "too_new": False, "unknown_sections": [],
           "unknown_fields": {}, "invalid": [], "app_version": None}
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        res["error"] = "Файл слишком большой для конфига Chimera."
        return res
    try:
        raw = json.loads(text)
    except ValueError:
        res["error"] = "Это не конфиг Chimera: файл не удалось прочитать."
        return res
    if not isinstance(raw, dict) or not isinstance(raw.get("schema"), int) or isinstance(raw.get("schema"), bool):
        res["error"] = "Это не конфиг Chimera: нет версии схемы."
        return res
    schema = raw["schema"]
    res["app_version"] = raw.get("app_version") if isinstance(raw.get("app_version"), str) else None
    if schema > SCHEMA:
        res.update(too_new=True, error=f"Конфиг создан более новой версией Chimera (схема {schema}). "
                                       "Обновите программу, чтобы его применить.")
        return res
    if schema < 1:
        res["error"] = "Неизвестная версия схемы конфига."
        return res
    min_v = raw.get("min_app_version")
    if isinstance(min_v, str) and version.parse(min_v) and version.parse(current_version) \
            and version.is_newer(min_v, current_version):
        res.update(too_new=True, error=f"Конфиг требует Chimera {min_v} или новее (у вас {current_version}). "
                                       "Обновите программу.")
        return res

    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, dict):
        sections_raw = {}
    sections = {}
    for sid, body in sections_raw.items():
        if sid not in SECTIONS:
            res["unknown_sections"].append(str(sid))
            continue
        clean, unknown = _clean_section(sid, body, res["invalid"])
        sections[sid] = clean
        if unknown:
            res["unknown_fields"][sid] = unknown
    res["unknown_sections"].sort()
    res["doc"] = {"schema": schema, "app_version": res["app_version"],
                  "min_app_version": min_v if isinstance(min_v, str) else None,
                  "sections": {s: sections[s] for s in SECTIONS if s in sections}}
    return res


# --- предпросмотр -----------------------------------------------------------------------------

def _same_provider(a: dict, b: dict) -> bool:
    return (a.get("name", "").strip().lower() == b.get("name", "").strip().lower()
            and sorted(a.get("servers") or []) == sorted(b.get("servers") or [])
            and (a.get("doh") or "") == (b.get("doh") or ""))


def _provider_line(p: dict) -> str:
    where = ", ".join((p.get("servers") or []) + ([p["doh"]] if p.get("doh") else []) + ([p["dot"]] if p.get("dot") else []))
    return f"«{p['name']}» ({where})"


def _known_lists(current: dict, doc_sections: dict) -> set[str]:
    have = set((current.get("known") or {}).get("list_names") or [])
    return have | set((doc_sections.get("lists") or {}).get("items") or {})


def preview(parsed: dict, current: dict) -> dict:
    """Что изменится у получателя. current — snapshot приёмника."""
    base = {"ok": False, "error": parsed.get("error"), "too_new": parsed.get("too_new", False),
            "app_version": parsed.get("app_version"), "sections": [], "needs_confirm": False,
            "unknown_sections": parsed.get("unknown_sections", []),
            "unknown_fields": parsed.get("unknown_fields", {}), "invalid": parsed.get("invalid", [])}
    doc = parsed.get("doc")
    if not doc:
        return base

    known = current.get("known") or {}
    have_lists = _known_lists(current, doc["sections"])
    out = []

    def add(sid, changes=(), confirm=(), skipped=()):
        out.append({"id": sid, "title": TITLES[sid], "provider_dependent": sid in PROVIDER_DEPENDENT,
                    "changes": list(changes), "confirm": list(confirm), "skipped": list(skipped)})

    for sid, data in doc["sections"].items():
        changes, confirm, skipped = [], [], []
        if sid == "lists":
            mine = current.get("lists") or {}
            for name, text in (data.get("items") or {}).items():
                if name not in mine:
                    changes.append(f"новый список «{name}»: {len(_entries(text))} записей")
                else:
                    extra = [e for e in _entries(text) if e not in set(_entries(mine[name]))]
                    if extra:
                        changes.append(f"«{name}»: добавится {len(extra)} записей")
        elif sid == "proxy":
            cur = current.get("proxy") or {}
            if "mode" in data and data["mode"] != cur.get("mode"):
                changes.append(f"режим: {cur.get('mode')} → {data['mode']}")
            for n in data.get("lists") or []:
                if n not in have_lists:
                    skipped.append(f"список «{n}» отсутствует у вас и не приложен")
            if "lists" in data and sorted(data["lists"]) != sorted(cur.get("lists") or []):
                changes.append("выбранные списки: " + (", ".join(data["lists"]) or "ничего"))
            if "apps" in data and sorted(data["apps"]) != sorted(cur.get("apps") or []):
                changes.append("приложения: " + (", ".join(data["apps"]) or "ничего"))
        elif sid in ("hosts", "dns"):
            mine = (current.get(sid) or {}).get("providers") or []
            for p in data.get("providers") or []:
                if not any(_same_provider(p, m) for m in mine):
                    confirm.append(f"чужой провайдер {_provider_line(p)}: подменяет ответы DNS")
            if sid == "hosts":
                imported_ids = {p["id"] for p in data.get("providers") or [] if p.get("id")}
                for pid, lst in (data.get("assignments") or {}).items():
                    if pid not in set(known.get("provider_ids") or []) | imported_ids:
                        skipped.append(f"привязка к неизвестному провайдеру «{pid}»")
                    else:
                        changes.append(f"«{pid}» ← {', '.join(lst)}")
        elif sid == "telegram":
            cur = current.get("telegram") or {}
            if "port" in data and data["port"] != cur.get("port"):
                changes.append(f"порт: {cur.get('port')} → {data['port']}")
            adv, cadv = data.get("advanced") or {}, cur.get("advanced") or {}
            for k in _TG_BOOLS:
                if k in adv and adv[k] != cadv.get(k):
                    changes.append(f"{k}: {cadv.get(k)} → {adv[k]}")
            for k in _TG_DOMAINS + ("fake_tls_domain",):
                if adv.get(k) and adv.get(k) != cadv.get(k):
                    val = ", ".join(adv[k]) if isinstance(adv[k], list) else adv[k]
                    confirm.append(f"домены-ретрансляторы ({k}): {val}")
            if adv.get("dc_redirects") and adv["dc_redirects"] != cadv.get("dc_redirects"):
                confirm.append("адреса дата-центров: " + ", ".join(f"{k}→{v}" for k, v in adv["dc_redirects"].items()))
        elif sid == "winws":
            cur = current.get("winws") or {}
            s = data.get("strategy")
            if s:
                if s not in set(known.get("strategies") or []):
                    skipped.append(f"стратегия «{s}» отсутствует в вашей версии")
                elif s != cur.get("strategy"):
                    changes.append(f"стратегия: {cur.get('strategy') or 'не выбрана'} → {s} (выбор, без запуска)")
            for n in data.get("lists") or []:
                if n not in have_lists:
                    skipped.append(f"список «{n}» отсутствует у вас и не приложен")
            g = data.get("game") or {}
            if g and g != {k: (cur.get("game") or {}).get(k) for k in g}:
                changes.append(f"игровой фильтр: {g.get('mode', '—')}")
            if "ipset" in data and data["ipset"] != cur.get("ipset"):
                changes.append(f"ipset: {cur.get('ipset')} → {data['ipset']}")
        add(sid, changes, confirm, skipped)

    base.update(ok=True, error=None, sections=out, needs_confirm=any(s["confirm"] for s in out))
    return base


# --- применение --------------------------------------------------------------------------------

def _backup(files, root: Path | None) -> str | None:
    files = [Path(f) for f in files if Path(f).exists()]
    if not files:
        return None
    root = Path(root) if root else paths.data_path("backups")
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # номер в пределах одной секунды — по максимуму существующих: после удаления старых
    # снимков счёт по количеству мог бы повториться и упереться в занятое имя
    taken = [int(d.name[len(stamp) + 1:len(stamp) + 4]) for d in root.iterdir()
             if d.is_dir() and d.name.startswith(stamp + "-") and d.name[len(stamp) + 1:len(stamp) + 4].isdigit()]
    dest = root / f"{stamp}-{max(taken, default=0) + 1:03d}-import"
    dest.mkdir()
    used = set()
    for f in files:
        name, n = f.name, 1
        while name in used:
            n += 1
            name = f"{f.stem}.{n}{f.suffix}"
        used.add(name)
        shutil.copy2(f, dest / name)
    olds = sorted(d for d in root.iterdir() if d.is_dir() and d.name.endswith("-import"))
    for d in olds[:-KEEP_BACKUPS]:
        shutil.rmtree(d, ignore_errors=True)
    return str(dest)


def apply(parsed: dict, sections, confirmed: bool, ops, backup_root: Path | None = None) -> dict:
    """Применяет выбранные разделы через ops. Перед этим копирует затрагиваемые файлы в
    data/backups/<время>-import/ (последние 10). Сбой шага не мешает остальным: он
    попадает в errors."""
    result = {"applied": {}, "skipped": {}, "errors": [], "backup": None}
    doc = parsed.get("doc")
    if not doc:
        result["errors"].append(parsed.get("error") or "Нечего применять.")
        return result

    chosen = [s for s in SECTIONS if s in set(sections) and s in doc["sections"]]
    current = ops.snapshot()
    mine_lists = dict(current.get("lists") or {})
    known = current.get("known") or {}

    touched = list((doc["sections"].get("lists") or {}).get("items", {})) if "lists" in chosen else []
    try:
        result["backup"] = _backup(ops.backup_files(chosen, touched), backup_root)
    except OSError as e:
        result["errors"].append(f"снимок файлов не создан: {e}")

    def record(sid, key, line):
        result[key].setdefault(sid, []).append(line)

    def step(sid, fn):
        try:
            fn()
        except Exception as e:
            result["errors"].append(f"{TITLES[sid]}: {e}")

    written_lists = set()
    id_map = {}    # id провайдера в файле -> id у нас

    if "lists" in chosen:
        def do_lists():
            for name, text in (doc["sections"]["lists"].get("items") or {}).items():
                if name not in mine_lists:
                    ops.list_write(name, text)
                    mine_lists[name] = text
                    record("lists", "applied", f"создан список «{name}»")
                else:
                    have = set(_entries(mine_lists[name]))
                    extra = [e for e in _entries(text) if e not in have]
                    if extra:
                        merged = mine_lists[name].rstrip("\n") + "\n" + "\n".join(extra) + "\n"
                        ops.list_write(name, merged)
                        mine_lists[name] = merged
                        record("lists", "applied", f"«{name}»: добавлено {len(extra)}")
                written_lists.add(name)
        step("lists", do_lists)

    def add_providers(sid, unblock_key):
        existing = (current.get(sid) or {}).get("providers") or []
        for p in doc["sections"][sid].get("providers") or []:
            same = next((m for m in existing if _same_provider(p, m)), None)
            if same:
                id_map[p.get("id") or p["name"]] = same.get("id") or p["name"]
                continue
            if not confirmed:
                record(sid, "skipped", f"пропущен чужой провайдер «{p['name']}»: нужно подтверждение")
                continue
            new_id = ops.add_provider({**p, "unblock": unblock_key})
            id_map[p.get("id") or p["name"]] = new_id
            record(sid, "applied", f"добавлен провайдер «{p['name']}»")

    if "dns" in chosen:
        step("dns", lambda: add_providers("dns", False))
    if "hosts" in chosen:
        def do_hosts():
            add_providers("hosts", True)
            merged = {k: list(v) for k, v in ((current.get("hosts") or {}).get("assignments") or {}).items()}
            ids = set(known.get("provider_ids") or [])
            changed = False
            for pid, lst in (doc["sections"]["hosts"].get("assignments") or {}).items():
                target = id_map.get(pid, pid if pid in ids else None)
                if target is None:
                    record("hosts", "skipped", f"привязка к неизвестному провайдеру «{pid}»")
                    continue
                for n in lst:
                    for other in merged:      # один список — один провайдер: приходящая привязка главнее
                        if n in merged[other]:
                            merged[other].remove(n)
                    merged.setdefault(target, []).append(n)
                changed = True
            if changed:
                ops.set_assignments({k: v for k, v in merged.items() if v})
                record("hosts", "applied", "привязки списков обновлены")
        step("hosts", do_hosts)

    if "proxy" in chosen:
        def do_proxy():
            d = doc["sections"]["proxy"]
            available = set(mine_lists) | written_lists
            lists = None
            if "lists" in d:
                lists = [n for n in d["lists"] if n in available]
                for n in d["lists"]:
                    if n not in available:
                        record("proxy", "skipped", f"список «{n}» отсутствует и не приложен")
            ops.set_proxy(d.get("mode"), lists, d.get("apps") if "apps" in d else None)
            record("proxy", "applied", "режим, списки и приложения прокси")
        step("proxy", do_proxy)

    if "telegram" in chosen:
        def do_telegram():
            d = doc["sections"]["telegram"]
            if "port" in d:
                ops.tg_set_port(d["port"])
                record("telegram", "applied", f"порт {d['port']}")
            adv = dict(d.get("advanced") or {})
            if not confirmed:
                for k in _TG_DOMAINS + ("fake_tls_domain", "dc_redirects"):
                    if adv.pop(k, None):
                        record("telegram", "skipped", f"{k}: нужно подтверждение")
            if adv:
                ops.tg_set_advanced(adv)
                record("telegram", "applied", "продвинутые настройки")
        step("telegram", do_telegram)

    if "winws" in chosen:
        def do_winws():
            d = doc["sections"]["winws"]
            available = set(mine_lists) | written_lists
            if d.get("strategy"):
                if d["strategy"] in set(known.get("strategies") or []):
                    ops.winws_select(d["strategy"])
                    record("winws", "applied", f"выбрана стратегия «{d['strategy']}» (без запуска)")
                else:
                    record("winws", "skipped", f"стратегия «{d['strategy']}» отсутствует в вашей версии")
            if "lists" in d:
                ops.winws_set_lists([n for n in d["lists"] if n in available])
                record("winws", "applied", "списки обхода DPI")
            g = d.get("game") or {}
            if g.get("mode"):
                ops.game_set(g["mode"], g.get("tcp"), g.get("udp"))
                record("winws", "applied", f"игровой фильтр: {g['mode']}")
            if d.get("ipset"):
                ops.ipset_set(d["ipset"])
                record("winws", "applied", f"ipset: {d['ipset']}")
        step("winws", do_winws)

    return result
