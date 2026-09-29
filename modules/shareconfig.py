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

from modules.i18n import LazyMap, t as _tr

import ipaddress
import json
import re
from pathlib import Path

from . import domains, version
from .provider_util import parse_servers, validate_doh, validate_host

SCHEMA = 1
SECTIONS = ("lists", "proxy", "hosts", "dns", "telegram", "winws")
DEFAULT_SECTIONS = ("lists", "proxy", "hosts", "dns", "telegram")
PROVIDER_DEPENDENT = ("winws",)   # настройки обхода DPI зависят от провайдера пользователя
TITLES = LazyMap(SECTIONS, "msg.share.section")

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
        invalid.append(_tr('msg.modules.shareconfig.expected_a_list_of_names', p0=f'{where}'))
        return None
    out = []
    for n in value:
        if isinstance(n, str) and domains.NAME_RE.match(n):
            out.append(n)
        else:
            invalid.append(_tr('msg.modules.shareconfig.invalid_name', p0=f'{where}', p1=f'{n}'))
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
        invalid.append(_tr('msg.modules.shareconfig.expected_an_object', p0=f'{where}'))
        return None
    name = str(p.get("name") or "").strip()
    if not name or len(name) > 64:
        invalid.append(_tr('msg.modules.shareconfig.missing_name', p0=f'{where}'))
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
        invalid.append(_tr('msg.modules.shareconfig.missing_ip_address_and_doh_dot', p0=f'{where}', p1=f'{name}'))
        return None
    pid = p.get("id") if isinstance(p.get("id"), str) and _ID_RE.match(p["id"]) else ""
    return {"id": pid, "name": name, "servers": servers, "ipv6": ipv6, "doh": doh, "dot": dot,
            "filter": bool(p.get("filter"))}


def _unknown(section: dict, allowed) -> list[str]:
    return sorted(k for k in section if k not in allowed)


def _clean_section(sid: str, raw, invalid) -> tuple[dict, list[str]]:
    """(нормализованный раздел, неизвестные поля). raw — объект из файла."""
    if not isinstance(raw, dict):
        invalid.append(_tr('msg.modules.shareconfig.expected_an_object', p0=f'{sid}'))
        return {}, []
    out, unknown = {}, []

    if sid == "lists":
        unknown = _unknown(raw, ("items",))
        items = raw.get("items")
        clean = {}
        if isinstance(items, dict):
            for name, text in list(items.items())[:MAX_LISTS]:
                if not (isinstance(name, str) and domains.NAME_RE.match(name)):
                    invalid.append(_tr('msg.modules.shareconfig.list_invalid_name', p0=f'{name}'))
                    continue
                if not isinstance(text, str) or text.count("\n") > MAX_LIST_LINES:
                    invalid.append(_tr('msg.modules.shareconfig.list_invalid_or_oversized_content', p0=f'{name}'))
                    continue
                cleaned, dropped = _clean_list_text(text)
                if dropped:
                    invalid.append(_tr('msg.modules.shareconfig.list_lines_with_invalid_characters_dropped', p0=f'{name}', p1=f'{dropped}'))
                clean[name] = cleaned
        elif items is not None:
            invalid.append(_tr('msg.modules.shareconfig.lists_items_expected_an_object'))
        out["items"] = clean

    elif sid == "proxy":
        unknown = _unknown(raw, ("mode", "lists", "apps"))
        if "mode" in raw:
            if raw["mode"] in _MODES:
                out["mode"] = raw["mode"]
            else:
                invalid.append(_tr('msg.modules.shareconfig.proxy_mode_unknown_mode', p0=f"{raw['mode']}"))
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
                        invalid.append(_tr('msg.modules.shareconfig.proxy_apps_invalid_name', p0=f'{a}'))
                out["apps"] = apps
            else:
                invalid.append(_tr('msg.modules.shareconfig.proxy_apps_expected_a_list'))

    elif sid in ("hosts", "dns"):
        unknown = _unknown(raw, ("assignments", "providers") if sid == "hosts" else ("providers",))
        provs = []
        if isinstance(raw.get("providers"), list):
            for i, p in enumerate(raw["providers"]):
                clean = _clean_provider(p, f"{sid}.providers[{i}]", invalid)
                if clean:
                    provs.append(clean)
        elif "providers" in raw:
            invalid.append(_tr('msg.modules.shareconfig.providers_expected_a_list', p0=f'{sid}'))
        out["providers"] = provs
        if sid == "hosts":
            assign = {}
            if isinstance(raw.get("assignments"), dict):
                for pid, lst in raw["assignments"].items():
                    if not (isinstance(pid, str) and _ID_RE.match(pid)):
                        invalid.append(_tr('msg.modules.shareconfig.hosts_assignments_invalid_provider', p0=f'{pid}'))
                        continue
                    names = _names(lst, f"hosts.assignments[{pid}]", invalid)
                    if names:
                        assign[pid] = names
            elif "assignments" in raw:
                invalid.append(_tr('msg.modules.shareconfig.hosts_assignments_expected_an_object'))
            out["assignments"] = assign

    elif sid == "telegram":
        unknown = _unknown(raw, ("port", "advanced"))
        port = raw.get("port")
        if "port" in raw:
            if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
                out["port"] = port
            else:
                invalid.append(_tr('msg.modules.shareconfig.telegram_port_invalid_port', p0=f'{port}'))
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
                        invalid.append(_tr('msg.modules.shareconfig.telegram_advanced_expected_yes_no', p0=f'{k}'))
            for k in _TG_DOMAINS:
                if k in adv_raw:
                    v = adv_raw[k]
                    if isinstance(v, list) and all(isinstance(d, str) for d in v):
                        adv[k] = list(v)
                    else:
                        invalid.append(_tr('msg.modules.shareconfig.telegram_advanced_expected_a_list_of_domains', p0=f'{k}'))
            if "fake_tls_domain" in adv_raw:
                v = adv_raw["fake_tls_domain"]
                if isinstance(v, str):
                    adv["fake_tls_domain"] = v.strip()
                else:
                    invalid.append(_tr('msg.modules.shareconfig.telegram_advanced_fake_tls_domain_expected_a_str'))
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
                            invalid.append(_tr('msg.modules.shareconfig.telegram_advanced_dc_redirects_invalid', p0=f'{dc}', p1=f'{ip}'))
                    adv["dc_redirects"] = clean
                else:
                    invalid.append(_tr('msg.modules.shareconfig.telegram_advanced_dc_redirects_expected_an_objec'))
            out["advanced"] = adv
        elif "advanced" in raw:
            invalid.append(_tr('msg.modules.shareconfig.telegram_advanced_expected_an_object'))

    elif sid == "winws":
        from .winws import filters
        unknown = _unknown(raw, ("strategy", "lists", "game", "ipset"))
        if "strategy" in raw and raw["strategy"] is not None:
            s = raw["strategy"]
            if isinstance(s, str) and _ID_RE.match(s):
                out["strategy"] = s
            else:
                invalid.append(_tr('msg.modules.shareconfig.winws_strategy_invalid_name', p0=f'{s}'))
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
                invalid.append(_tr('msg.modules.shareconfig.winws_game_mode_invalid_value', p0=f"{game['mode']}"))
            for k in ("tcp", "udp"):
                if k in game:
                    try:
                        g[k] = filters.validate_game_range(game[k])
                    except (ValueError, TypeError) as e:
                        invalid.append(f"winws.game.{k}: {e}")
            out["game"] = g
        elif "game" in raw:
            invalid.append(_tr('msg.modules.shareconfig.winws_game_expected_an_object'))
        if "ipset" in raw:
            if raw["ipset"] in _IPSET_MODES:
                out["ipset"] = raw["ipset"]
            else:
                invalid.append(_tr('msg.modules.shareconfig.winws_ipset_invalid_mode', p0=f"{raw['ipset']}"))

    return out, unknown


def parse(text: str, current_version: str | None = None) -> dict:
    """Разбор файла. doc — нормализованный документ или None; error — что сказать
    пользователю, если применять нечего."""
    current_version = current_version if current_version is not None else version.VERSION
    res = {"doc": None, "error": None, "too_new": False, "unknown_sections": [],
           "unknown_fields": {}, "invalid": [], "app_version": None}
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        res["error"] = _tr('msg.modules.shareconfig.the_file_is_too_large_for_a_chimera_configuratio')
        return res
    try:
        raw = json.loads(text)
    except ValueError:
        res["error"] = _tr('msg.modules.shareconfig.not_a_chimera_configuration_could_not_read_the_f')
        return res
    if not isinstance(raw, dict) or not isinstance(raw.get("schema"), int) or isinstance(raw.get("schema"), bool):
        res["error"] = _tr('msg.modules.shareconfig.not_a_chimera_configuration_missing_schema_versi')
        return res
    schema = raw["schema"]
    res["app_version"] = raw.get("app_version") if isinstance(raw.get("app_version"), str) else None
    if schema > SCHEMA:
        res.update(too_new=True, error=_tr('msg.modules.shareconfig.this_configuration_was_created_by_a_newer_chimer', p0=f'{schema}'))
        return res
    if schema < 1:
        res["error"] = _tr('msg.modules.shareconfig.unknown_configuration_schema_version')
        return res
    min_v = raw.get("min_app_version")
    if isinstance(min_v, str) and version.parse(min_v) and version.parse(current_version) \
            and version.is_newer(min_v, current_version):
        res.update(too_new=True, error=_tr('msg.modules.shareconfig.the_configuration_requires_chimera_or_newer_curr', p0=f'{min_v}', p1=f'{current_version}'))
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
                    changes.append(_tr('msg.modules.shareconfig.new_list_entries', p0=f'{name}', p1=f'{len(_entries(text))}'))
                else:
                    extra = [e for e in _entries(text) if e not in set(_entries(mine[name]))]
                    if extra:
                        changes.append(_tr('msg.modules.shareconfig.entries_will_be_added', p0=f'{name}', p1=f'{len(extra)}'))
        elif sid == "proxy":
            cur = current.get("proxy") or {}
            if "mode" in data and data["mode"] != cur.get("mode"):
                changes.append(_tr('msg.modules.shareconfig.mode', p0=f"{cur.get('mode')}", p1=f"{data['mode']}"))
            for n in data.get("lists") or []:
                if n not in have_lists:
                    skipped.append(_tr('msg.modules.shareconfig.list_is_missing_and_was_not_included', p0=f'{n}'))
            if "lists" in data and sorted(data["lists"]) != sorted(cur.get("lists") or []):
                changes.append(_tr('msg.modules.shareconfig.selected_lists') + (", ".join(data["lists"]) or _tr('msg.modules.shareconfig.none')))
            if "apps" in data and sorted(data["apps"]) != sorted(cur.get("apps") or []):
                changes.append(_tr('msg.modules.shareconfig.applications') + (", ".join(data["apps"]) or _tr('msg.modules.shareconfig.none')))
        elif sid in ("hosts", "dns"):
            mine = (current.get(sid) or {}).get("providers") or []
            for p in data.get("providers") or []:
                if not any(_same_provider(p, m) for m in mine):
                    confirm.append(_tr('msg.modules.shareconfig.external_provider_overrides_dns_responses', p0=f'{_provider_line(p)}'))
            if sid == "hosts":
                imported_ids = {p["id"] for p in data.get("providers") or [] if p.get("id")}
                for pid, lst in (data.get("assignments") or {}).items():
                    if pid not in set(known.get("provider_ids") or []) | imported_ids:
                        skipped.append(_tr('msg.modules.shareconfig.assignment_to_unknown_provider', p0=f'{pid}'))
                    else:
                        changes.append(f"«{pid}» ← {', '.join(lst)}")
        elif sid == "telegram":
            cur = current.get("telegram") or {}
            if "port" in data and data["port"] != cur.get("port"):
                changes.append(_tr('msg.modules.shareconfig.port_54', p0=f"{cur.get('port')}", p1=f"{data['port']}"))
            adv, cadv = data.get("advanced") or {}, cur.get("advanced") or {}
            for k in _TG_BOOLS:
                if k in adv and adv[k] != cadv.get(k):
                    changes.append(f"{k}: {cadv.get(k)} → {adv[k]}")
            for k in _TG_DOMAINS + ("fake_tls_domain",):
                if adv.get(k) and adv.get(k) != cadv.get(k):
                    val = ", ".join(adv[k]) if isinstance(adv[k], list) else adv[k]
                    confirm.append(_tr('msg.modules.shareconfig.relay_domains', p0=f'{k}', p1=f'{val}'))
            if adv.get("dc_redirects") and adv["dc_redirects"] != cadv.get("dc_redirects"):
                confirm.append(_tr('msg.modules.shareconfig.datacenter_addresses') + ", ".join(f"{k}→{v}" for k, v in adv["dc_redirects"].items()))
        elif sid == "winws":
            cur = current.get("winws") or {}
            s = data.get("strategy")
            if s:
                if s not in set(known.get("strategies") or []):
                    skipped.append(_tr('msg.modules.shareconfig.strategy_is_missing_from_this_version', p0=f'{s}'))
                elif s != cur.get("strategy"):
                    changes.append(_tr('msg.modules.shareconfig.strategy_selection_without_starting',
                        p0=f"{cur.get('strategy') or _tr('msg.modules.shareconfig.not_selected')}",
                        p1=f'{s}',
                    ))
            for n in data.get("lists") or []:
                if n not in have_lists:
                    skipped.append(_tr('msg.modules.shareconfig.list_is_missing_and_was_not_included', p0=f'{n}'))
            g = data.get("game") or {}
            if g and g != {k: (cur.get("game") or {}).get(k) for k in g}:
                changes.append(_tr('msg.modules.shareconfig.game_filter', p0=f"{g.get('mode', '—')}"))
            if "ipset" in data and data["ipset"] != cur.get("ipset"):
                changes.append(f"ipset: {cur.get('ipset')} → {data['ipset']}")
        add(sid, changes, confirm, skipped)

    base.update(ok=True, error=None, sections=out, needs_confirm=any(s["confirm"] for s in out))
    return base


# --- применение --------------------------------------------------------------------------------

def _backup(files, root: Path | None) -> str | None:
    from modules import configbackups
    backup_id = configbackups.create_files(files, root)
    return str(configbackups.root_path(root) / backup_id) if backup_id else None


def apply(parsed: dict, sections, confirmed: bool, ops, backup_root: Path | None = None) -> dict:
    """Применяет выбранные разделы через ops. Перед этим копирует затрагиваемые файлы в
    data/backups/<время>-import/ (последние 10). Сбой шага не мешает остальным: он
    попадает в errors."""
    result = {"applied": {}, "skipped": {}, "errors": [], "backup": None}
    doc = parsed.get("doc")
    if not doc:
        result["errors"].append(parsed.get("error") or _tr('msg.modules.shareconfig.nothing_to_apply'))
        return result

    chosen = [s for s in SECTIONS if s in set(sections) and s in doc["sections"]]
    current = ops.snapshot()
    mine_lists = dict(current.get("lists") or {})
    known = current.get("known") or {}

    touched = list((doc["sections"].get("lists") or {}).get("items", {})) if "lists" in chosen else []
    try:
        files = ops.backup_files(chosen, touched)
        if files and hasattr(ops, "backup_state"):
            from modules import configbackups
            backup_id = configbackups.create_snapshot(ops.backup_state(chosen, touched), backup_root, kind="import")
            result["backup"] = str(configbackups.root_path(backup_root) / backup_id)
        else:
            result["backup"] = _backup(files, backup_root)
    except Exception as e:
        result["errors"].append(_tr('msg.modules.shareconfig.could_not_create_a_file_snapshot', p0=f'{e}'))
        return result

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
                    record("lists", "applied", _tr('msg.modules.shareconfig.created_list', p0=f'{name}'))
                else:
                    have = set(_entries(mine_lists[name]))
                    extra = [e for e in _entries(text) if e not in have]
                    if extra:
                        merged = mine_lists[name].rstrip("\n") + "\n" + "\n".join(extra) + "\n"
                        ops.list_write(name, merged)
                        mine_lists[name] = merged
                        record("lists", "applied", _tr('msg.modules.shareconfig.added', p0=f'{name}', p1=f'{len(extra)}'))
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
                record(sid, "skipped", _tr('msg.modules.shareconfig.skipped_external_provider_confirmation_required', p0=f"{p['name']}"))
                continue
            new_id = ops.add_provider({**p, "unblock": unblock_key})
            id_map[p.get("id") or p["name"]] = new_id
            record(sid, "applied", _tr('msg.modules.shareconfig.added_provider', p0=f"{p['name']}"))

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
                    record("hosts", "skipped", _tr('msg.modules.shareconfig.assignment_to_unknown_provider', p0=f'{pid}'))
                    continue
                for n in lst:
                    for other in merged:      # один список — один провайдер: приходящая привязка главнее
                        if n in merged[other]:
                            merged[other].remove(n)
                    merged.setdefault(target, []).append(n)
                changed = True
            if changed:
                ops.set_assignments({k: v for k, v in merged.items() if v})
                record("hosts", "applied", _tr('msg.modules.shareconfig.list_assignments_updated'))
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
                        record("proxy", "skipped", _tr('msg.modules.shareconfig.list_is_missing_and_was_not_included_45', p0=f'{n}'))
            ops.set_proxy(d.get("mode"), lists, d.get("apps") if "apps" in d else None)
            record("proxy", "applied", _tr('msg.modules.shareconfig.proxy_mode_lists_and_applications'))
        step("proxy", do_proxy)

    if "telegram" in chosen:
        def do_telegram():
            d = doc["sections"]["telegram"]
            if "port" in d:
                ops.tg_set_port(d["port"])
                record("telegram", "applied", _tr('msg.modules.shareconfig.port', p0=f"{d['port']}"))
            adv = dict(d.get("advanced") or {})
            if not confirmed:
                for k in _TG_DOMAINS + ("fake_tls_domain", "dc_redirects"):
                    if adv.pop(k, None):
                        record("telegram", "skipped", _tr('msg.modules.shareconfig.confirmation_required', p0=f'{k}'))
            if adv:
                ops.tg_set_advanced(adv)
                record("telegram", "applied", _tr('msg.modules.shareconfig.advanced_settings'))
        step("telegram", do_telegram)

    if "winws" in chosen:
        def do_winws():
            d = doc["sections"]["winws"]
            available = set(mine_lists) | written_lists
            if d.get("strategy"):
                if d["strategy"] in set(known.get("strategies") or []):
                    ops.winws_select(d["strategy"])
                    record("winws", "applied", _tr('msg.modules.shareconfig.selected_strategy_without_starting', p0=f"{d['strategy']}"))
                else:
                    record("winws", "skipped", _tr('msg.modules.shareconfig.strategy_is_missing_from_this_version', p0=f"{d['strategy']}"))
            if "lists" in d:
                ops.winws_set_lists([n for n in d["lists"] if n in available])
                record("winws", "applied", _tr('msg.modules.shareconfig.dpi_bypass_lists'))
            g = d.get("game") or {}
            if g.get("mode"):
                ops.game_set(g["mode"], g.get("tcp"), g.get("udp"))
                record("winws", "applied", _tr('msg.modules.shareconfig.game_filter', p0=f"{g['mode']}"))
            if d.get("ipset"):
                ops.ipset_set(d["ipset"])
                record("winws", "applied", f"ipset: {d['ipset']}")
        step("winws", do_winws)

    return result
