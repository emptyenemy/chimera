"""Runtime readers keep seeing complete files while replacements are prepared."""

import copy
import io
import shutil
import threading
from pathlib import Path
from functools import partial

import pytest

from modules import domains, fileutil
from modules.proxy import manager as proxy
from modules.winws import filters, manager as winws


@pytest.fixture(params=[
    "winws-domains", "winws-ips", "proxy-domains", "proxy-ips", "proxy-config", "pac",
    "ipset-none", "ipset-any", "ipset-load", "ipset-save",
    "ipset-update-backup", "ipset-update-active", "fake",
])
def runtime_write(request, tmp_path, monkeypatch):
    kind = request.param
    monkeypatch.setattr(domains, "split_lists", lambda names: (["new.example"], ["203.0.113.0/24"]))
    if kind.startswith("winws"):
        host, ips = tmp_path / "domains.txt", tmp_path / "ips.txt"
        monkeypatch.setattr(winws, "USER_HOSTLIST_PATH", host)
        monkeypatch.setattr(winws, "USER_IPSET_PATH", ips)
        instance = winws.WinwsManager.__new__(winws.WinwsManager)
        instance.config = {"lists": ["sample"]}
        host.write_bytes(b"old.example\r\n")
        ips.write_bytes(b"192.0.2.0/24\r\n")
        target = host if kind == "winws-domains" else ips
        write = instance._regenerate_user_hostlist
    elif kind == "proxy-config":
        target = tmp_path / "singbox-config.json"
        executable = tmp_path / "sing-box.exe"
        target.write_bytes(b'{"previous": true}\r\n')
        executable.write_bytes(b"not executable")
        monkeypatch.setattr(proxy, "CONFIG_PATH", target)
        monkeypatch.setattr(proxy, "SINGBOX_EXE", executable)
        monkeypatch.setattr(proxy.ProxyManager, "running", property(lambda self: False))
        instance = proxy.ProxyManager.__new__(proxy.ProxyManager)
        instance._lock = threading.RLock()
        instance.config = copy.deepcopy(proxy.DEFAULTS)
        monkeypatch.setattr(instance, "build_config", lambda: {"new": True})
        monkeypatch.setattr(instance, "_write_rulesets", lambda: None)

        class StopBeforeLaunch(Exception):
            pass

        def stop():
            raise StopBeforeLaunch

        monkeypatch.setattr(instance, "_write_pac", stop)
        monkeypatch.setattr(proxy.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Unexpected process launch"))

        def write():
            with pytest.raises(StopBeforeLaunch):
                instance.start()
    elif kind.startswith("proxy") or kind == "pac":
        host, ips, pac = tmp_path / "domains.json", tmp_path / "ips.json", tmp_path / "proxy.pac"
        monkeypatch.setattr(proxy, "DOMAINS_RULESET_PATH", host)
        monkeypatch.setattr(proxy, "IPS_RULESET_PATH", ips)
        monkeypatch.setattr(proxy, "PAC_PATH", pac)
        instance = proxy.ProxyManager.__new__(proxy.ProxyManager)
        instance.config = copy.deepcopy(proxy.DEFAULTS)
        host.write_bytes(b'{"version":3,"rules":[{"domain_suffix":["old.example"]}]}')
        ips.write_bytes(b'{"version":3,"rules":[{"ip_cidr":["192.0.2.0/24"]}]}')
        pac.write_bytes(b'function FindProxyForURL() { return "DIRECT"; }\r\n')
        target = pac if kind == "pac" else host if kind == "proxy-domains" else ips
        write = instance._write_pac if kind == "pac" else instance._write_rulesets
    elif kind.startswith("ipset"):
        active, backup = tmp_path / "ipset.txt", tmp_path / "ipset.txt.backup"
        monkeypatch.setattr(filters, "IPSET_FILE", active)
        monkeypatch.setattr(filters, "IPSET_BACKUP", backup)
        active.write_bytes(b"192.0.2.0/24\r\n")
        backup.write_bytes(b"198.51.100.0/24\r\n")
        target = active
        if kind == "ipset-load":
            active.write_bytes((filters.IPSET_PLACEHOLDER + "\r\n").encode())
            write = partial(filters.set_ipset_mode, "loaded")
        elif kind in {"ipset-none", "ipset-save"}:
            write = partial(filters.set_ipset_mode, "none")
            if kind == "ipset-save":
                target = backup
        elif kind == "ipset-any":
            write = partial(filters.set_ipset_mode, "any")
        else:
            monkeypatch.setattr(filters.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"203.0.113.0/24\n"))
            write = filters.update_ipset
            if kind == "ipset-update-backup":
                target = backup
                active.write_bytes((filters.IPSET_PLACEHOLDER + "\r\n").encode())
    else:
        monkeypatch.setattr(filters, "ASSETS_DIR", tmp_path)
        target = tmp_path / filters.FAKE_SLOTS["discord"][0]
        target.write_bytes(b"old\x00\xff\r\n")
        (tmp_path / "candidate.bin").write_bytes(bytes(range(256)) + b"\r\n\x00")
        write = partial(filters.set_fake, "discord", "candidate")
    return write, target


def test_runtime_reader_sees_complete_previous_file(runtime_write, monkeypatch):
    write, target = runtime_write
    before = target.read_bytes()
    ready, release = threading.Event(), threading.Event()
    errors = []
    real_text, real_copy, real_replace = Path.write_text, shutil.copyfile, fileutil.os.replace

    def partial(data):
        with target.open("wb") as stream:
            stream.write(data[:1])
            stream.flush()
            ready.set()
            assert release.wait(3)
            stream.write(data[1:])

    def direct_text(path, text, *args, **kwargs):
        if path == target:
            return partial(text.encode("utf-8"))
        return real_text(path, text, *args, **kwargs)

    def direct_copy(source, destination, *args, **kwargs):
        if Path(destination) == target:
            return partial(Path(source).read_bytes())
        return real_copy(source, destination, *args, **kwargs)

    def replace(source, destination):
        if Path(destination) == target:
            ready.set()
            assert release.wait(3)
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "write_text", direct_text)
    monkeypatch.setattr(shutil, "copyfile", direct_copy)
    monkeypatch.setattr(fileutil.os, "replace", replace)

    def run():
        try:
            write()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert ready.wait(2)
        assert target.read_bytes() == before
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert target.read_bytes() != before
    assert not list(target.parent.glob("*.tmp"))


def test_runtime_write_failure_preserves_previous_file_and_cleans_staging(runtime_write, monkeypatch):
    write, target = runtime_write
    before = target.read_bytes()
    real_text, real_copy, real_replace = Path.write_text, shutil.copyfile, fileutil.os.replace

    def fail():
        raise OSError("Simulated disk failure")

    def direct_text(path, text, *args, **kwargs):
        if path == target:
            path.write_bytes(text.encode("utf-8")[:1])
            fail()
        return real_text(path, text, *args, **kwargs)

    def direct_copy(source, destination, *args, **kwargs):
        if Path(destination) == target:
            target.write_bytes(Path(source).read_bytes()[:1])
            fail()
        return real_copy(source, destination, *args, **kwargs)

    def replace(source, destination):
        if Path(destination) == target:
            fail()
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "write_text", direct_text)
    monkeypatch.setattr(shutil, "copyfile", direct_copy)
    monkeypatch.setattr(fileutil.os, "replace", replace)
    with pytest.raises(OSError, match="Simulated disk failure"):
        write()
    assert target.read_bytes() == before
    assert not list(target.parent.glob("*.tmp"))


def test_fake_replacement_preserves_all_bytes_and_line_endings(tmp_path, monkeypatch):
    monkeypatch.setattr(filters, "ASSETS_DIR", tmp_path)
    content = bytes(range(256)) + b"\r\n\n\x00"
    (tmp_path / "candidate.bin").write_bytes(content)
    result = filters.set_fake("game", "candidate")
    assert (tmp_path / filters.FAKE_SLOTS["game"][0]).read_bytes() == content
    assert result["slots"]["game"]["current"] == "candidate"


@pytest.mark.parametrize("name", ["../outside", "nested/candidate", r"nested\candidate", "ACTIVE_GAME_UDP", "directory"])
def test_fake_replacement_only_accepts_candidates_from_assets(tmp_path, monkeypatch, name):
    assets = tmp_path / "assets"
    assets.mkdir()
    monkeypatch.setattr(filters, "ASSETS_DIR", assets)
    (tmp_path / "outside.bin").write_bytes(b"outside")
    (assets / "nested").mkdir()
    (assets / "nested" / "candidate.bin").write_bytes(b"nested")
    (assets / "directory.bin").mkdir()
    active = assets / filters.FAKE_SLOTS["game"][0]
    active.write_bytes(b"previous")
    with pytest.raises(FileNotFoundError):
        filters.set_fake("game", name)
    assert active.read_bytes() == b"previous"
    assert not list(assets.glob("*.tmp"))


def test_fake_catalog_ignores_directories_named_like_blobs(tmp_path, monkeypatch):
    monkeypatch.setattr(filters, "ASSETS_DIR", tmp_path)
    (tmp_path / "directory.bin").mkdir()
    (tmp_path / "candidate.bin").write_bytes(b"blob")
    assert filters.fake_candidates() == ["candidate"]
    assert filters.fakes_state()["candidates"] == ["candidate"]


def test_rulesets_do_not_overwrite_another_writers_fixed_temp_file(tmp_path, monkeypatch):
    host, ips = tmp_path / "domains.json", tmp_path / "ips.json"
    staging = tmp_path / "domains.json.tmp"
    staging.write_bytes(b"other writer")
    monkeypatch.setattr(proxy, "DOMAINS_RULESET_PATH", host)
    monkeypatch.setattr(proxy, "IPS_RULESET_PATH", ips)
    instance = proxy.ProxyManager.__new__(proxy.ProxyManager)
    monkeypatch.setattr(instance, "_split", lambda: (["new.example"], []))
    instance._write_rulesets()
    assert staging.read_bytes() == b"other writer"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["domains.json", "domains.json.tmp", "ips.json"]


def test_runtime_write_retries_a_briefly_locked_target(runtime_write, monkeypatch):
    write, target = runtime_write
    real_replace = fileutil.os.replace
    attempts = []

    def replace(source, destination):
        if Path(destination) == target:
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError("Simulated temporary lock")
        return real_replace(source, destination)

    monkeypatch.setattr(fileutil.os, "replace", replace)
    monkeypatch.setattr(fileutil.time, "sleep", lambda seconds: None)
    write()
    assert len(attempts) == 3
    assert not list(target.parent.glob("*.tmp"))


def test_ipset_mode_roundtrip_preserves_exact_saved_bytes(tmp_path, monkeypatch):
    active, backup = tmp_path / "ipset.txt", tmp_path / "ipset.txt.backup"
    monkeypatch.setattr(filters, "IPSET_FILE", active)
    monkeypatch.setattr(filters, "IPSET_BACKUP", backup)
    content = b"192.0.2.0/24\r\n198.51.100.0/24\n"
    active.write_bytes(content)
    assert filters.set_ipset_mode("none")["state"] == "none"
    assert backup.read_bytes() == content
    assert filters.set_ipset_mode("loaded")["state"] == "loaded"
    assert active.read_bytes() == content


@pytest.mark.parametrize("mode", ["any", "none", "loaded"])
def test_ipset_download_preserves_selected_mode(tmp_path, monkeypatch, mode):
    active, backup = tmp_path / "ipset.txt", tmp_path / "ipset.txt.backup"
    monkeypatch.setattr(filters, "IPSET_FILE", active)
    monkeypatch.setattr(filters, "IPSET_BACKUP", backup)
    before = {"any": b"", "none": (filters.IPSET_PLACEHOLDER + "\r\n").encode(), "loaded": b"192.0.2.0/24\r\n"}[mode]
    active.write_bytes(before)
    monkeypatch.setattr(filters.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"198.51.100.0/24\n203.0.113.0/24\n"))
    result = filters.update_ipset()
    assert result["state"] == mode
    assert result["downloaded"] == 2
    assert result["stored"] == 2
    if mode == "loaded":
        assert active.read_bytes() == backup.read_bytes()
    else:
        assert active.read_bytes() == before
