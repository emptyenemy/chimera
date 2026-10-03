"""State saves keep previous settings readable and unchanged when a write fails."""

import copy
import importlib
import json
import threading

import pytest

from modules import dns_providers, fileutil
from modules.hosts.manager import HostsManager


@pytest.fixture(params=["proxy", "tgproxy", "winws"])
def manager(request, tmp_path, monkeypatch):
    module = importlib.import_module(f"modules.{request.param}.manager")
    cls = getattr(module, {"proxy": "ProxyManager", "tgproxy": "TgProxy", "winws": "WinwsManager"}[request.param])
    instance = cls.__new__(cls)
    instance.config = copy.deepcopy(module.DEFAULTS)
    instance._lock = threading.RLock()
    if request.param == "tgproxy":
        instance.config["secret"] = "a" * 32
    path = tmp_path / "state.json"
    monkeypatch.setattr(module, "STATE_PATH", path)
    monkeypatch.setattr(instance, "state", lambda: copy.deepcopy(instance.config))
    monkeypatch.setattr(cls, "running", property(lambda self: False))
    monkeypatch.setattr(instance, "restart", lambda: pytest.fail("Unexpected restart"), raising=False)
    monkeypatch.setattr("modules.domains.list_info", lambda: [{"name": "sample"}])
    instance._save()
    return request.param, module, instance, path


def test_readers_see_previous_complete_state_while_save_is_prepared(manager, monkeypatch):
    _, _, instance, path = manager
    before = json.loads(path.read_text(encoding="utf-8"))
    instance.config = {**instance.config, "autostart": True}
    ready, release = threading.Event(), threading.Event()
    errors = []
    real_write = type(path).write_text
    real_replace = fileutil.os.replace

    def direct_write(target, text, *args, **kwargs):
        if target != path:
            return real_write(target, text, *args, **kwargs)
        with target.open("w", encoding="utf-8") as stream:
            stream.write(text[:1])
            stream.flush()
            ready.set()
            assert release.wait(3)
            stream.write(text[1:])

    def replace(source, target):
        if str(target) == str(path):
            ready.set()
            assert release.wait(3)
        return real_replace(source, target)

    monkeypatch.setattr(type(path), "write_text", direct_write)
    monkeypatch.setattr(fileutil.os, "replace", replace)

    def save():
        try:
            instance._save()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=save)
    worker.start()
    try:
        assert ready.wait(1)
        assert json.loads(path.read_text(encoding="utf-8")) == before
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert json.loads(path.read_text(encoding="utf-8"))["autostart"]
    assert list(path.parent.iterdir()) == [path]


def test_failed_setting_save_keeps_memory_file_and_side_effects_unchanged(manager, monkeypatch):
    kind, _, instance, path = manager
    before = copy.deepcopy(instance.config)
    saved = path.read_bytes()
    real_write = type(path).write_text

    def fail_replace(*args, **kwargs):
        raise OSError("Simulated disk failure")

    def fail_direct(target, *args, **kwargs):
        if target == path:
            raise OSError("Simulated disk failure")
        return real_write(target, *args, **kwargs)

    monkeypatch.setattr(fileutil.os, "replace", fail_replace)
    monkeypatch.setattr(type(path), "write_text", fail_direct)
    with pytest.raises(OSError):
        if kind == "tgproxy":
            instance.set_config("localhost", 2443, "b" * 32, True)
        else:
            instance.set_autostart(True)
    assert instance.config == before
    assert path.read_bytes() == saved
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("saved", [None, ["invalid"], 15, True])
def test_non_object_state_uses_defaults_without_type_errors(manager, saved):
    kind, _, instance, path = manager
    path.write_text(json.dumps(saved), encoding="utf-8")
    result = instance._load()
    assert result["autostart"] is False
    assert isinstance(result, dict)
    if kind == "tgproxy":
        assert len(result["secret"]) == 32


def test_hosts_save_keeps_previous_file_until_replacement(tmp_path, monkeypatch):
    path = tmp_path / "hosts.json"
    instance = HostsManager(state_path=path, hosts_path=tmp_path / "hosts")
    before = {"background": {"refresh_interval": 21600}}
    instance._save_state(before)
    replacements = []
    real = fileutil.os.replace

    def replace(source, target):
        replacements.append(True)
        assert json.loads(path.read_text(encoding="utf-8")) == before
        real(source, target)

    monkeypatch.setattr(fileutil.os, "replace", replace)
    instance._save_state({"background": {"refresh_interval": 7200}})
    assert replacements == [True]
    assert instance.background_options()["refresh_interval"] == 7200


def test_dns_provider_save_keeps_previous_file_until_replacement(tmp_path, monkeypatch):
    path = tmp_path / "providers.json"
    monkeypatch.setattr(dns_providers, "USER_PATH", path)
    before = [{"id": "first", "name": "First"}]
    dns_providers._save_user(before)
    replacements = []
    real = fileutil.os.replace

    def replace(source, target):
        replacements.append(True)
        assert dns_providers._load_user() == before
        real(source, target)

    monkeypatch.setattr(fileutil.os, "replace", replace)
    dns_providers._save_user([{"id": "second", "name": "Second"}])
    assert replacements == [True]


@pytest.mark.parametrize("saved", [None, {}, 15, [None, 15, "bad", {}]])
def test_malformed_dns_provider_collection_does_not_crash(tmp_path, monkeypatch, saved):
    path = tmp_path / "providers.json"
    monkeypatch.setattr(dns_providers, "USER_PATH", path)
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert dns_providers._load_user() == []
    assert all(item["builtin"] for item in dns_providers.load_all())


@pytest.mark.parametrize("case", [0, 1, 2])
def test_all_setting_edits_keep_confirmed_state_on_disk_failure(manager, monkeypatch, case):
    kind, module, instance, path = manager
    before = copy.deepcopy(instance.config)
    saved = path.read_bytes()
    strategy = path.parent / "alternate.txt"
    strategy.write_text("--filter-tcp=443", encoding="utf-8")
    if kind == "winws":
        monkeypatch.setattr(module, "STRATEGIES_DIR", path.parent)
        monkeypatch.setattr(instance, "refresh_user_lists", lambda: pytest.fail("Unexpected generated file write"))
    if kind == "proxy":
        monkeypatch.setattr(instance, "reload_lists", lambda: pytest.fail("Unexpected live reload"))

    def fail(*args, **kwargs):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr(module, "atomic_write_text", fail)
    with pytest.raises(OSError):
        if kind == "proxy":
            if case == 0:
                instance.set_link("vless://test-id@example.com:443?security=none")
            elif case == 1:
                instance.set_apps(["Example.exe"])
            else:
                instance.set_mode("split")
        elif kind == "tgproxy":
            if case == 0:
                instance.set_advanced({"fake_tls_domain": "example.com"})
            elif case == 1:
                instance.regen_secret()
            else:
                instance.restore_config({**before, "autostart": True})
        else:
            if case == 0:
                instance.set_lists(["sample"])
            elif case == 1:
                instance.select_strategy("alternate")
            else:
                instance.restore_config({**before, "autostart": True})
    assert instance.config == before
    assert path.read_bytes() == saved


def test_pending_save_does_not_expose_unconfirmed_settings(manager, monkeypatch):
    kind, _, instance, path = manager
    before = copy.deepcopy(instance.config)
    ready, release = threading.Event(), threading.Event()
    real = fileutil.os.replace
    errors = []

    def replace(source, target):
        ready.set()
        assert release.wait(3)
        return real(source, target)

    monkeypatch.setattr(fileutil.os, "replace", replace)

    def save():
        try:
            if kind == "tgproxy":
                instance.set_config("localhost", 2443, "b" * 32, True)
            else:
                instance.set_autostart(True)
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=save)
    worker.start()
    try:
        assert ready.wait(1)
        assert instance.state() == before
        assert json.loads(path.read_text(encoding="utf-8")) == before
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert instance.config["autostart"]


def test_malformed_dns_entries_do_not_hide_valid_providers(tmp_path, monkeypatch):
    path = tmp_path / "providers.json"
    monkeypatch.setattr(dns_providers, "USER_PATH", path)
    valid = {"id": "custom", "name": "Custom", "servers": ["192.0.2.1"]}
    path.write_text(json.dumps([None, {}, valid, "bad"]), encoding="utf-8")
    assert dns_providers._load_user() == [valid]
    assert dns_providers.get("custom")["builtin"] is False


def test_manager_default_collections_are_independent(manager):
    _, module, instance, path = manager
    path.unlink()
    first, second = instance._load(), instance._load()
    for key, value in first.items():
        if isinstance(value, list):
            assert value is not second[key] and value is not module.DEFAULTS[key]
        if isinstance(value, dict):
            assert value is not second[key] and value is not module.DEFAULTS[key]


@pytest.mark.parametrize("port", [1443.5, True, False, None, [], {}, "1443.5", "bad", float("inf")])
def test_telegram_invalid_port_is_rejected_before_any_setting_changes(tmp_path, monkeypatch, port):
    module = importlib.import_module("modules.tgproxy.manager")
    path = tmp_path / "state.json"
    monkeypatch.setattr(module, "STATE_PATH", path)
    instance = module.TgProxy()
    before, saved = copy.deepcopy(instance.config), path.read_bytes()
    with pytest.raises(ValueError) as error:
        instance.set_config("localhost", port, "b" * 32, True)
    assert error.value.code == "err.tgproxy.manager.the_port_must_be_a_number_from_1_to_65535"
    assert instance.config == before
    assert path.read_bytes() == saved


@pytest.mark.parametrize("port", [1, 65535, 2443.0, "1", "65535", " 2443 ", "0002443"])
def test_telegram_integer_ports_still_save(tmp_path, monkeypatch, port):
    module = importlib.import_module("modules.tgproxy.manager")
    path = tmp_path / "state.json"
    monkeypatch.setattr(module, "STATE_PATH", path)
    instance = module.TgProxy()
    monkeypatch.setattr(instance, "state", lambda: copy.deepcopy(instance.config))
    instance.set_config("localhost", port, "b" * 32, False)
    assert instance.config["port"] == int(port)
    assert json.loads(path.read_text(encoding="utf-8"))["port"] == int(port)
