"""Local configuration snapshots and restoration through the live application layer.

Old import snapshots contain flat copies of state files. New snapshots add a manifest
with digests and absent files, so importing a new list can also be undone exactly.
Snapshot data is never executed; only known, validated settings reach the managers.
"""

import hashlib
import json
import re
import shutil
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from modules import appconfig, domains, paths, shareconfig
from modules.errors import ChimeraValueError
from modules.i18n import t

SCHEMA = 1
KEEP = 10
MAX_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
ID_RE = re.compile(r"^\d{8}-\d{6}-\d{3,8}-(?:import|restore)$")
FILES = {"proxy.json": "proxy", "tgproxy.json": "telegram", "hosts.json": "hosts",
         "dns_providers.user.json": "dns", "winws.json": "winws", "config.json": "config",
         "winws-filters.json": "filters"}
STATE_FILES = {v: k for k, v in FILES.items()}
SECTIONS = ("lists", "dns", "hosts", "proxy", "telegram", "winws", "config", "filters")
_LOCK = threading.RLock()
FIELD_TITLES = {("config", "theme"): "msg.backup.field.theme",
                ("config", "lang"): "msg.backup.field.lang",
                ("filters", "content"): "msg.backup.field.ipset_content",
                ("filters", "ipset"): "msg.backup.field.ipset_mode",
                ("filters", "loaded"): "msg.backup.field.ipset_loaded"}


def _bad(name=""):
    raise ChimeraValueError("err.backup.invalid", name=name)


def root_path(root=None):
    return Path(root) if root is not None else paths.data_path("backups")


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _section(name):
    if name in FILES:
        return FILES[name]
    if name.endswith(".txt") and domains.NAME_RE.fullmatch(name[:-4]):
        return "lists"
    _bad()


def _json(raw, name):
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError):
        _bad(name)


def _bool(value):
    if not isinstance(value, bool):
        _bad()
    return value


def _port(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        _bad()
    return value


def _config(raw):
    if not isinstance(raw, dict):
        _bad()
    # Unknown settings have no restore setter; never carry them into runtime config.
    known = set(appconfig.DEFAULTS) | {"ui_port", "tray_hint_shown", "dns_probe", "game_filter",
                                     "game_filter_tcp", "game_filter_udp"}
    if "frontend" in raw and raw["frontend"] not in ("legacy", "next"):
        _bad()
    if set(raw) - known - {"frontend"}:
        _bad()
    out = {**appconfig.DEFAULTS, **{k: v for k, v in raw.items() if k != "frontend"}}
    for key in ("auto_elevate", "close_to_tray", "update_check", "tray_hint_shown"):
        if key in out:
            _bool(out[key])
    choices = {"theme": appconfig.THEMES, "lang": ("auto", "ru", "en"),
               "interface": ("ui", "tui", "service"), "ui_backend": ("pyside6", "pywebview", "browser"),
               "update_channel": ("stable", "beta")}
    for key, allowed in choices.items():
        if out.get(key) not in allowed:
            _bad()
    if "ui_port" in out:
        _port(out["ui_port"])
    if "dns_probe" in out:
        spec = out["dns_probe"]
        if not isinstance(spec, dict) or set(spec) - {"bypass", "ad"}:
            _bad()
        vals = spec.get("bypass", [])
        if not isinstance(vals, list):
            _bad()
        for val in [*vals, spec.get("ad", "")]:
            if not isinstance(val, str) or len(val) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]*", val):
                _bad()
    from modules.winws import filters
    if "game_filter" in out and out["game_filter"] not in filters.GAME_MODES:
        _bad()
    for key in ("game_filter_tcp", "game_filter_udp"):
        if key in out:
            out[key] = filters.validate_game_range(out[key])
    return out


def normalize(sid, raw):
    """Strictly validate one supported state file, without leaking rejected values."""
    from modules.hosts.background import DEFAULT_OPTIONS
    from modules.proxy import manager as proxy_manager, parser
    from modules.tgproxy import manager as tg_manager
    from modules.winws import manager as winws_manager
    try:
        if sid == "config":
            return _config(raw)
        if sid == "filters":
            import ipaddress
            if not isinstance(raw, dict) or set(raw) != {"ipset", "content", "loaded"}:
                _bad()
            if raw["ipset"] not in shareconfig._IPSET_MODES:
                _bad()
            for field in ("content", "loaded"):
                text = raw[field]
                if text is None:
                    continue
                if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE_BYTES:
                    _bad()
                for line in text.splitlines():
                    value = line.split("#", 1)[0].strip()
                    if value:
                        ipaddress.ip_network(value, strict=False)
            return dict(raw)
        if sid == "dns":
            if not isinstance(raw, list) or len(raw) > 200:
                _bad()
            result, ids = [], set()
            for item in raw:
                if not isinstance(item, dict) or set(item) - set(shareconfig._PROVIDER_KEYS) - {"unblock", "builtin"}:
                    _bad()
                invalid = []
                clean = shareconfig._clean_provider(item, "dns", invalid)
                if invalid or not clean or not clean["id"] or clean["id"] in ids:
                    _bad()
                clean["unblock"] = _bool(item.get("unblock", False))
                clean["filter"] = _bool(item.get("filter", False))
                ids.add(clean["id"])
                result.append(clean)
            return result
        if not isinstance(raw, dict):
            _bad()
        if sid == "hosts":
            if set(raw) - {"assignments", "enabled", "background", "entries", "health", "last_switch", "switch_log"}:
                _bad()
            assignments = raw.get("assignments", {})
            if not isinstance(assignments, dict):
                _bad()
            for pid, value in assignments.items():
                if not isinstance(pid, str) or not shareconfig._ID_RE.fullmatch(pid):
                    _bad()
                if value is not True and (not isinstance(value, list) or any(
                        not isinstance(n, str) or not domains.NAME_RE.fullmatch(n) for n in value)):
                    _bad()
            background = raw.get("background", {})
            if not isinstance(background, dict) or set(background) - set(DEFAULT_OPTIONS):
                _bad()
            background = {**DEFAULT_OPTIONS, **background}
            for key in ("refresh_enabled", "check_enabled", "autoswitch_enabled"):
                _bool(background[key])
            for key in ("refresh_interval", "check_interval"):
                if not isinstance(background[key], int) or isinstance(background[key], bool) or background[key] < 1:
                    _bad()
            order = background["provider_order"]
            if not isinstance(order, list) or any(not isinstance(i, str) or not shareconfig._ID_RE.fullmatch(i) for i in order):
                _bad()
            return {"assignments": assignments, "enabled": _bool(raw.get("enabled", True)),
                    "background": background}
        defaults = {"proxy": proxy_manager.DEFAULTS, "telegram": tg_manager.DEFAULTS,
                    "winws": winws_manager.DEFAULTS}[sid]
        if set(raw) - set(defaults):
            _bad()
        full = {**defaults, **raw}
        _bool(full["autostart"])
        portable = dict(full)
        if sid == "proxy":
            if not isinstance(full["link"], str):
                _bad()
            if full["link"]:
                parser.parse_link(full["link"])
            _port(full["socks_port"])
            portable = {k: full[k] for k in ("mode", "lists", "apps")}
        elif sid == "telegram":
            import ipaddress
            from modules.provider_util import validate_host
            if not isinstance(full["host"], str) or not full["host"]:
                _bad()
            try:
                ipaddress.ip_address(full["host"])
            except ValueError:
                if full["host"] != "localhost":
                    validate_host(full["host"])
            _port(full["port"])
            full["secret"] = tg_manager._normalize_secret(full["secret"])
            portable = {"port": full["port"], "advanced": {k: full[k] for k in shareconfig._TG_KEYS}}
        elif sid == "winws":
            portable = {"strategy": full["last_strategy"], "lists": full["lists"]}
            if full["last_strategy"] is None:
                portable.pop("strategy")
        invalid = []
        clean, unknown = shareconfig._clean_section(sid, portable, invalid)
        if invalid or unknown:
            _bad()
        if sid == "proxy":
            full.update(clean)
        elif sid == "telegram":
            full.update(clean.get("advanced", {}))
        else:
            full["lists"] = clean.get("lists", [])
        return full
    except Exception:
        _bad(STATE_FILES.get(sid, sid))


def load(backup_id, root=None):
    base = root_path(root).resolve()
    if not isinstance(backup_id, str) or not ID_RE.fullmatch(backup_id):
        _bad()
    directory = base / backup_id
    if not directory.is_dir() or _is_link(directory) or directory.resolve().parent != base:
        _bad()
    children = list(directory.iterdir())
    if len(children) > shareconfig.MAX_LISTS + len(FILES) + 1:
        _bad()
    blobs = {}
    size = 0
    for item in children:
        if _is_link(item) or not item.is_file() or item.resolve().parent != directory.resolve():
            _bad()
        if item.name != "manifest.json":
            _section(item.name)
        if item.stat().st_size > MAX_FILE_BYTES:
            _bad(item.name)
        data = item.read_bytes()
        size += len(data)
        if len(data) > MAX_FILE_BYTES or size > MAX_BYTES:
            _bad()
        blobs[item.name] = data
    legacy = "manifest.json" not in blobs
    if legacy:
        entries = [{"name": name, "exists": True} for name in blobs]
        created = datetime.strptime(backup_id[:15], "%Y%m%d-%H%M%S").astimezone(UTC)
        created_at = created.isoformat(timespec="seconds").replace("+00:00", "Z")
    else:
        manifest = _json(blobs.pop("manifest.json"), "manifest.json")
        if (not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
                or isinstance(manifest.get("schema"), bool) or manifest.get("kind") != backup_id.rsplit("-", 1)[1]):
            _bad()
        entries = manifest.get("entries")
        created_at = manifest.get("created_at")
        if not isinstance(entries, list) or not isinstance(created_at, str):
            _bad()
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            _bad()
    states, lists, seen, obsolete = {}, {}, set(), []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("exists"), bool):
            _bad()
        name = item["name"]
        sid = _section(name)
        if name in seen:
            _bad()
        seen.add(name)
        exists = item["exists"]
        if exists:
            if name not in blobs:
                _bad(name)
            raw = blobs[name]
            if not legacy and hashlib.sha256(raw).hexdigest() != item.get("sha256"):
                _bad(name)
            if sid == "lists":
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeError:
                    _bad(name)
                _, dropped = shareconfig._clean_list_text(text)
                if dropped or text.count("\n") > shareconfig.MAX_LIST_LINES:
                    _bad(name)
                lists[name[:-4]] = text
            else:
                decoded = _json(raw, name)
                if sid == "config" and isinstance(decoded, dict) and "frontend" in decoded:
                    obsolete.append("frontend")
                states[sid] = normalize(sid, decoded)
        elif sid == "lists":
            if name in blobs:
                _bad(name)
            lists[name[:-4]] = None
        else:
            if name in blobs:
                _bad(name)
            # An absent state file means its defaults, not deletion of live JSON.
            from modules.proxy.manager import DEFAULTS as PROXY_DEFAULTS
            from modules.winws.manager import DEFAULTS as WINWS_DEFAULTS
            defaults = {"proxy": PROXY_DEFAULTS, "winws": WINWS_DEFAULTS, "dns": [],
                        "hosts": {}, "config": {}}
            if sid not in defaults:
                _bad(name)
            states[sid] = normalize(sid, defaults[sid])
    if set(blobs) - seen or not (states or lists):
        _bad()
    return {"id": backup_id, "kind": backup_id.rsplit("-", 1)[1], "created_at": created_at,
            "states": states, "lists": lists, "legacy": legacy, "obsolete_fields": obsolete}


def _publish(blobs, root, kind):
    if kind not in ("import", "restore") or not blobs or len(blobs) > shareconfig.MAX_LISTS + len(FILES):
        _bad()
    if any(blob is not None and len(blob) > MAX_FILE_BYTES for blob in blobs.values()):
        _bad()
    if sum(len(blob) for blob in blobs.values() if blob is not None) > MAX_BYTES - MAX_FILE_BYTES:
        _bad()
    base = root_path(root)
    base.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    stamp = now.astimezone().strftime("%Y%m%d-%H%M%S")
    taken = [int(p.name.split("-")[2]) for p in base.iterdir() if ID_RE.fullmatch(p.name) and p.name.startswith(stamp + "-")]
    backup_id = f"{stamp}-{max(taken, default=0) + 1:03d}-{kind}"
    entries = []
    temp = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=base))
    try:
        for name, blob in blobs.items():
            entry = {"name": name, "exists": blob is not None}
            if blob is not None:
                (temp / name).write_bytes(blob)
                entry["sha256"] = hashlib.sha256(blob).hexdigest()
            entries.append(entry)
        manifest = {"schema": SCHEMA, "kind": kind,
                    "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "sections": [sid for sid in SECTIONS if any(_section(name) == sid for name in blobs)],
                    "entries": entries}
        (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.rename(base / backup_id)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    old = sorted(p for p in base.iterdir() if ID_RE.fullmatch(p.name) and p.is_dir() and not _is_link(p))
    for p in old[:-KEEP]:
        if p.resolve().parent == base.resolve():
            shutil.rmtree(p)
    return backup_id


def create_files(files, root=None, kind="import"):
    """Snapshot touched files, including those that did not exist before import."""
    files = list(dict.fromkeys(Path(f) for f in files))
    if not files:
        return None
    blobs = {}
    for f in files:
        _section(f.name)
        if f.name in blobs or _is_link(f):
            _bad()
        if f.exists() and f.stat().st_size > MAX_FILE_BYTES:
            _bad(f.name)
        blobs[f.name] = f.read_bytes() if f.exists() else None
    with _LOCK:
        return _publish(blobs, root, kind)


def create_snapshot(snapshot, root=None, kind="restore"):
    blobs = {STATE_FILES[sid]: (json.dumps(normalize(sid, value), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
             for sid, value in snapshot["states"].items()}
    for name, text in snapshot["lists"].items():
        blobs[f"{name}.txt"] = None if text is None else text.encode("utf-8")
    for name, text in snapshot["lists"].items():
        _section(f"{name}.txt")
        if text is not None and (shareconfig._clean_list_text(text)[1] or text.count("\n") > shareconfig.MAX_LIST_LINES):
            _bad()
    with _LOCK:
        return _publish(blobs, root, kind)


def list_backups(root=None):
    base = root_path(root)
    if not base.exists():
        return []
    result = []
    for path in sorted(base.iterdir(), reverse=True):
        if not ID_RE.fullmatch(path.name):
            continue
        entry = {"id": path.name, "created_at": None, "kind": path.name.rsplit("-", 1)[1],
                 "sections": [], "valid": False, "error": None}
        try:
            backup = load(path.name, root)
            entry.update(created_at=backup["created_at"], valid=True,
                         sections=[sid for sid in SECTIONS if sid in backup["states"] or (sid == "lists" and backup["lists"])])
        except Exception:
            entry["error"] = t("err.backup.invalid", name="")
        result.append(entry)
    return result


def _preview(backup, ops):
    ops.validate_backup(backup)
    current = ops.backup_snapshot(backup)
    sections = []
    secret_changed = False
    for sid in SECTIONS:
        changes = []
        if sid == "lists" and backup["lists"]:
            for name, text in backup["lists"].items():
                old = current["lists"].get(name)
                if old == text:
                    continue
                key = "msg.backup.list_delete" if text is None else "msg.backup.list_replace"
                changes.append(t(key, name=name))
        elif sid in backup["states"]:
            old, value = current["states"].get(sid), backup["states"][sid]
            if isinstance(value, dict):
                for field in sorted(value):
                    if isinstance(old, dict) and old.get(field) == value[field]:
                        continue
                    sensitive = field in ("link", "secret", "host")
                    secret_changed |= sensitive
                    label = t(FIELD_TITLES[(sid, field)]) if (sid, field) in FIELD_TITLES else field
                    changes.append(t("msg.backup.secret_change" if sensitive else "msg.backup.setting_change", field=label))
            elif old != value:
                changes.append(t("msg.backup.providers_replace", count=len(value)))
        else:
            continue
        title = (t("msg.backup.config_title") if sid == "config" else
                 t("msg.backup.filters_title") if sid == "filters" else shareconfig.TITLES[sid])
        sections.append({"id": sid, "title": title, "changes": changes})
    warnings = [t("msg.backup.legacy_warning")] if backup["legacy"] else []
    if backup.get("obsolete_fields"):
        warnings.append(t("msg.backup.obsolete_warning"))
    if "config" in backup["states"] and any(backup["states"]["config"].get(k) != current["states"]["config"].get(k)
                                              for k in ("interface", "ui_backend", "ui_port")):
        warnings.append(t("msg.backup.restart_warning"))
    return {"id": backup["id"], "ok": True, "error": None, "errors": [], "sections": sections,
            "requires_admin": ops.backup_requires_admin(backup), "secrets_changed": secret_changed,
            "warnings": warnings}


def preview(backup_id, ops, root=None):
    try:
        return _preview(load(backup_id, root), ops)
    except Exception:
        error = t("err.backup.invalid", name="")
        return {"id": backup_id if isinstance(backup_id, str) and ID_RE.fullmatch(backup_id) else None,
                "ok": False, "error": error, "errors": [error], "sections": [],
                "requires_admin": False, "secrets_changed": False, "warnings": []}


def restore(backup_id, confirmed, ops, root=None):
    result = {"id": backup_id if isinstance(backup_id, str) and ID_RE.fullmatch(backup_id) else None,
              "restored": [], "backup": None, "errors": [], "rolled_back": False, "rollback_errors": []}
    with _LOCK:
        try:
            backup = load(backup_id, root)
            pv = _preview(backup, ops)
            if confirmed is not True:
                result["errors"].append(t("msg.backup.confirm_required"))
                return result
            if pv["requires_admin"] and not ops.backup_is_admin():
                result["errors"].append(t("msg.backup.admin_required"))
                return result
            before = ops.backup_snapshot(backup)
            result["backup"] = create_snapshot(before, root)
        except Exception:
            result["errors"].append(t("msg.backup.prepare_failed"))
            return result
        try:
            ops.restore_snapshot(backup)
            result["restored"] = [s["id"] for s in pv["sections"]]
        except Exception:
            result["errors"].append(t("msg.backup.apply_failed"))
            try:
                ops.restore_snapshot(before, rollback=True)
                result["rolled_back"] = True
            except Exception:
                result["rollback_errors"].append(t("msg.backup.rollback_failed"))
    return result
