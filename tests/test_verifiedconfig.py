import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import configbackups as backups, domains, fileutil, verifiedconfig
from modules.errors import ChimeraValueError
from tests.test_configbackups import LINK, SECRET, live as live
from ui import api as api_mod
from ui.trials import TrialOps


def create(live, check=None, context=None):
    return verifiedconfig.create(live.ops, ["youtube.com", "discord.com"],
                                 check or (lambda name: {"status": "ok"}),
                                 context or (lambda: {"running": True}), live.root)


def test_success_persists_full_snapshot_and_only_public_check_metadata(live):
    reply = create(live)
    assert reply["saved"] and reply["error"] is None
    assert reply["checks"] == [{"domain": name, "status": "ok"} for name in ("youtube.com", "discord.com")]
    assert verifiedconfig.state(live.root)["backup"] == reply["backup"]
    snapshot = backups.load(reply["backup"]["id"], live.root)
    assert snapshot["complete_lists"] and snapshot["states"]["proxy"]["link"] == LINK
    assert set(snapshot["states"]) == set(backups.SECTIONS) - {"lists"}
    assert backups.list_backups(live.root)[0]["verified"]
    for public in (reply, verifiedconfig.state(live.root), backups.list_backups(live.root)):
        assert LINK not in json.dumps(public) and SECRET not in json.dumps(public)
    assert LINK not in (live.root / verifiedconfig.MARKER).read_text(encoding="utf-8")


@pytest.mark.parametrize("status", ["challenge", "denied", "blocked", "dns", "error", "unknown"])
def test_failed_or_uncertain_site_keeps_previous_verified_snapshot(live, status):
    previous = create(live)["backup"]
    count = len(backups.list_backups(live.root))
    reply = create(live, check=lambda name: {"status": "ok" if name == "youtube.com" else status})
    assert not reply["saved"] and reply["error"] and reply["checks"][1]["status"] != "ok"
    assert verifiedconfig.state(live.root)["backup"] == previous
    assert len(backups.list_backups(live.root)) == count


def test_probe_exception_does_not_expose_secrets_or_replace_previous(live):
    previous = create(live)["backup"]
    def fail(name):
        raise RuntimeError(LINK + SECRET)
    reply = create(live, check=fail)
    assert not reply["saved"] and all(c["status"] == "error" for c in reply["checks"])
    assert LINK not in json.dumps(reply) and SECRET not in json.dumps(reply)
    assert verifiedconfig.state(live.root)["backup"] == previous


def test_slow_probe_is_bounded_and_never_marks_partial_success(live, monkeypatch):
    monkeypatch.setattr(verifiedconfig, "MAX_SECONDS", 0.03)
    release = threading.Event()
    def slow(name):
        release.wait(3)
        return {"status": "ok"}
    try:
        reply = create(live, check=slow)
        assert not reply["saved"] and all(c["status"] == "timeout" for c in reply["checks"])
        assert not verifiedconfig.state(live.root)["backup"]
    finally:
        release.set()


def test_direct_list_edit_during_checks_prevents_marking_stale_snapshot(live):
    previous = create(live)["backup"]
    def changed(name):
        if name == "youtube.com":
            domains.save_raw("discord", "new.example\n")
        return {"status": "ok"}
    reply = create(live, check=changed)
    assert not reply["saved"] and reply["error"]
    assert verifiedconfig.state(live.root)["backup"] == previous
    assert domains.read_raw("discord") == "new.example\n"


def test_runtime_changed_during_successful_checks_prevents_marking(live):
    calls = []
    def context():
        calls.append(True)
        return {"running": len(calls) == 1}
    reply = create(live, context=context)
    assert not reply["saved"] and reply["error"] and not verifiedconfig.state(live.root)["backup"]


def test_pinned_snapshot_survives_history_pruning_and_replacement(live):
    first = create(live)["backup"]["id"]
    for _ in range(backups.KEEP + 2):
        backups.create_manual(live.ops, live.root)
    assert backups.load(first, live.root)
    assert len(backups.list_backups(live.root)) == backups.KEEP + 1
    second = create(live)["backup"]["id"]
    assert second != first and verifiedconfig.state(live.root)["backup"]["id"] == second
    assert [b["id"] for b in backups.list_backups(live.root) if b["verified"]] == [second]


def test_pointer_write_failure_keeps_old_verified_snapshot(live, monkeypatch):
    previous = create(live)["backup"]
    replace = fileutil.os.replace
    def fail_marker(source, target):
        if Path(target).name == verifiedconfig.MARKER:
            raise OSError(LINK)
        return replace(source, target)
    monkeypatch.setattr(fileutil.os, "replace", fail_marker)
    with pytest.raises(ChimeraValueError) as exc:
        create(live)
    assert exc.value.code == "err.verified.save" and LINK not in str(exc.value)
    assert verifiedconfig.state(live.root)["backup"] == previous
    assert not list(live.root.glob(verifiedconfig.MARKER + ".*"))


def test_modified_manifest_invalidates_verification_even_with_valid_file_hashes(live):
    backup = create(live)["backup"]["id"]
    manifest = live.root / backup / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    assert backups.load(backup, live.root)
    assert verifiedconfig.state(live.root)["error"] and verifiedconfig.state(live.root)["backup"] is None
    assert not any(b["verified"] for b in backups.list_backups(live.root))
    assert verifiedconfig.pinned_id(live.root) == backup


def test_missing_damaged_or_incomplete_snapshot_is_not_offered_for_restore(live):
    assert verifiedconfig.state(live.root) == {"backup": None, "error": None}
    backup = create(live)["backup"]["id"]
    (live.root / backup / "config.json").unlink()
    assert verifiedconfig.state(live.root)["error"] and verifiedconfig.state(live.root)["backup"] is None
    (live.root / verifiedconfig.MARKER).write_text('{"schema":true}', encoding="utf-8")
    assert verifiedconfig.state(live.root)["error"]


@pytest.mark.parametrize("selected", [[], ["a.com"] * 7, ["https://a.com"], ["*.a.com"], ["localhost"], [1], None, "a.com"])
def test_invalid_domains_are_rejected_before_probes_or_files(live, selected):
    with pytest.raises(ChimeraValueError):
        verifiedconfig.create(live.ops, selected, lambda name: pytest.fail("unexpected probe"), lambda: {}, live.root)
    assert not live.root.exists()


def test_domains_are_case_normalized_and_deduplicated():
    assert verifiedconfig.names(["YouTube.com", "youtube.com", "discord.com"]) == ["youtube.com", "discord.com"]


def test_api_verifies_then_existing_preview_and_restore_keep_current_snapshot(live, monkeypatch):
    monkeypatch.setattr(TrialOps, "check", lambda self, domain: {"status": "ok"})
    reply = json.loads(live.api.dispatch("config_verify", json.dumps([["youtube.com"]])))
    assert reply["ok"] and reply["data"]["saved"]
    backup_id = reply["data"]["backup"]["id"]
    live.api.proxy.config["mode"] = "split"
    preview = live.api.config_backup_preview(backup_id)["data"]
    assert preview["ok"] and preview["requires_admin"]
    assert live.api.config_backup_restore(backup_id, False)["data"]["errors"]
    restored = live.api.config_backup_restore(backup_id, True)["data"]
    assert not restored["errors"] and restored["backup"]
    assert live.api.proxy.config["mode"] == "pac"
    assert backups.load(restored["backup"])["states"]["proxy"]["mode"] == "split"
    assert live.api.config_verified()["data"]["backup"]["id"] == backup_id


def test_verification_is_blocked_during_trial_and_foreign_processes(live, monkeypatch):
    live.api._trial = SimpleNamespace(active={"id": "trial", "phase": "pending"}, state=lambda: {"active": {"phase": "pending"}})
    monkeypatch.setattr(TrialOps, "check", lambda self, name: pytest.fail("unexpected probe"))
    assert live.api.config_verify(["youtube.com"])["code"] == "err.trial.busy"
    live.api._trial = None
    live.api.proxy.flag = True
    live.api.proxy.own = False
    assert not live.api.config_verify(["youtube.com"])["ok"]
    assert not live.root.exists()


def test_service_owner_and_language_are_forwarded(live, monkeypatch):
    live.api._service_owned = False
    monkeypatch.setattr(api_mod.service, "is_running", lambda: True)
    calls = []
    owner = SimpleNamespace(api=lambda method, *args: calls.append((method, *args)) or {"owner": True})
    from modules.cli import client
    monkeypatch.setattr(client, "connect", lambda: owner)
    assert live.api.config_verify(["youtube.com"], "en")["data"] == {"owner": True}
    assert live.api.config_verified("en")["data"] == {"owner": True}
    assert calls == [("config_verify", ["youtube.com"], "en"), ("config_verified", "en")]
    assert api_mod.Api.is_read("config_verified") and not api_mod.Api.is_read("config_verify")


def test_api_rejects_hosts_refresh_during_checks_and_pending_dns_trial(live, monkeypatch):
    def refresh(self, domain):
        live.api.hosts.hosts_path.write_bytes(b"# hosts changed during checks\n")
        return {"status": "ok"}
    monkeypatch.setattr(TrialOps, "check", refresh)
    reply = live.api.config_verify(["youtube.com"])
    assert reply["ok"] and not reply["data"]["saved"] and reply["data"]["error"]
    assert not live.api.config_verified()["data"]["backup"]
    live.api.dns = SimpleNamespace(trials=lambda: [{"adapter": 1}])
    assert live.api.config_verify(["youtube.com"])["code"] == "err.trial.busy"
