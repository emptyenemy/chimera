"""A pinned full snapshot, tied to successful checks of the captured configuration."""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime

from modules import configbackups as backups, control, domains, trials
from modules.errors import ChimeraValueError
from modules.fileutil import atomic_write_text
from modules.i18n import t

MAX_SECONDS = 8
MARKER = "verified.json"
STATUSES = {"ok", "challenge", "denied", "blocked", "dns", "error", "timeout"}


def names(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 6:
        raise ChimeraValueError("err.verified.domains")
    result = []
    for value in values:
        if not isinstance(value, str) or not trials.DOMAIN_RE.fullmatch(value.lower()):
            raise ChimeraValueError("err.verified.domains")
        if value.lower() not in result:
            result.append(value.lower())
    return result


def _read(root=None):
    path = backups.root_path(root) / MARKER
    if not path.exists() and not backups._is_link(path):
        return None
    try:
        if backups._is_link(path) or path.stat().st_size > 16384:
            raise ValueError
        value = json.loads(path.read_bytes())
        if (not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1
                or not isinstance(value.get("id"), str) or not backups.ID_RE.fullmatch(value["id"])
                or not value["id"].endswith("-manual") or not isinstance(value.get("checks"), list)
                or not isinstance(value.get("manifest_sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", value["manifest_sha256"])):
            raise ValueError
        checks = value["checks"]
        if any(not isinstance(c, dict) or set(c) != {"domain", "status"} or c["status"] != "ok" for c in checks):
            raise ValueError
        checked_names = [c["domain"] for c in checks]
        if names(checked_names) != checked_names:
            raise ValueError
        checked_at = datetime.fromisoformat(value["checked_at"])
        if checked_at.tzinfo is None:
            raise ValueError
        return value
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ChimeraValueError("err.verified.invalid") from None


def pinned_id(root=None):
    """Pruning protects the pointed-to snapshot, even if its files were damaged."""
    try:
        value = _read(root)
        return value["id"] if value else None
    except ChimeraValueError:
        return None


def state(root=None):
    with backups._LOCK:
        try:
            value = _read(root)
            if value is None:
                return {"backup": None, "error": None}
            snapshot = backups.load(value["id"], root)
            manifest = backups.root_path(root) / value["id"] / "manifest.json"
            if (not snapshot["complete_lists"] or set(snapshot["states"]) != set(backups.SECTIONS) - {"lists"}
                    or hashlib.sha256(manifest.read_bytes()).hexdigest() != value["manifest_sha256"]):
                raise ValueError
            return {"backup": {"id": value["id"], "checked_at": value["checked_at"], "checks": value["checks"]}, "error": None}
        except Exception:
            return {"backup": None, "error": t("err.verified.invalid")}


def _capture(ops):
    snapshot = ops.backup_state(backups.SECTIONS, domains.available_lists())
    snapshot["complete_lists"] = True
    return snapshot


def _checks(check, selected):
    pool = ThreadPoolExecutor(max_workers=len(selected), thread_name_prefix="config-verify")
    try:
        futures = [pool.submit(check, domain) for domain in selected]
        done, _ = wait(futures, timeout=MAX_SECONDS)
        results = []
        for domain, future in zip(selected, futures, strict=True):
            status = "timeout"
            if future in done:
                try:
                    status = future.result().get("status", "error")
                    if status not in STATUSES:
                        status = "error"
                except Exception:
                    status = "error"
            results.append({"domain": domain, "status": status})
        return results
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def create(ops, selected, check, context, root=None):
    selected = names(selected)
    with backups._LOCK:
        before, runtime = _capture(ops), context()
        ops.validate_backup(before)
        checks = _checks(check, selected)
        result = {"saved": False, "checks": checks, "backup": None, "error": None}
        if any(c["status"] != "ok" for c in checks):
            result["error"] = t("err.verified.checks")
            return result
        if _capture(ops) != before or context() != runtime:
            result["error"] = t("err.verified.changed")
            return result
        backup_id = None
        try:
            backup_id = backups.create_snapshot(before, root, kind="manual", prune=False)
            backups.load(backup_id, root)
            base = backups.root_path(root)
            value = {"schema": 1, "id": backup_id, "checks": checks,
                     "checked_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                     "manifest_sha256": hashlib.sha256((base / backup_id / "manifest.json").read_bytes()).hexdigest()}
            # A unique temp file and replace preserve the previous pointer on failure.
            atomic_write_text(base / MARKER, json.dumps(value, ensure_ascii=False) + "\n",
                              prepare=control._restrict_permissions)
        except Exception:
            # Keep an unpinned snapshot on failure: the previous verified pointer is untouched.
            raise ChimeraValueError("err.verified.save") from None
        result.update(saved=True, backup={"id": backup_id, "checked_at": value["checked_at"], "checks": checks})
        try:
            backups._prune(backups.root_path(root))
        except OSError:
            pass  # The verified snapshot has already been published successfully.
        return result
