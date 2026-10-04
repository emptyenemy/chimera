"""Стратегии и списки по воздуху: выбор выпуска, предпросмотр, свои правки не трогаются."""

import hashlib
import io
import json
import zipfile

import pytest

from modules import dataupdate
from modules.dataupdate import DataUpdater, is_data_path
from modules.errors import ChimeraError


def h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeGithub:
    """Выпуски GitHub в памяти: data-релизы с архивом и манифестом, плюс обычный релиз программы."""

    def __init__(self):
        self.releases = [{"tag_name": "v1.1.0", "assets": [{"name": "Chimera-1.1.0-win64.zip"}]}]
        self.blobs = {}

    def publish(self, version, files: dict, min_app=None, extra=None, tamper=None):
        manifest = {"schema": 1, "version": version, "files": {k: h(v) for k, v in files.items()}}
        if min_app:
            manifest["min_app"] = min_app
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in {**files, **(extra or {})}.items():
                z.writestr(name, tamper.get(name, data) if tamper else data)
        zip_bytes, manifest_bytes = buf.getvalue(), json.dumps(manifest).encode()
        assets = []
        for name, body in ((f"chimera-data-{version}.zip", zip_bytes), (f"chimera-data-{version}.json", manifest_bytes)):
            url = f"https://example.invalid/{name}"
            self.blobs[url] = body
            assets.append({"name": name, "browser_download_url": url, "size": len(body), "digest": f"sha256:{h(body)}"})
        self.releases.insert(0, {"tag_name": f"data-{version}", "assets": assets})

    def fetch(self, url):
        return self.releases

    def opener(self, req, timeout=None):
        return io.BytesIO(self.blobs[req.full_url])


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "app"
    (root / "strategies" / "hostlists").mkdir(parents=True)
    (root / "lists").mkdir()
    shipped_files = {"strategies/general.txt": b"--a\n", "lists/youtube.txt": b"youtube.com\n",
                     "strategies/hostlists/list-general.txt": b"discord.com\n"}
    for rel, data in shipped_files.items():
        (root / rel).write_bytes(data)
    (root / "lists" / "mine.txt").write_bytes(b"my.example\n")      # свой список, в данных его нет
    dataupdate.write_shipped(root, "2026.10.01")
    gh = FakeGithub()
    updater = DataUpdater(root, state=tmp_path / "state.json", app_version="1.1.0", frozen=True,
                          fetch=gh.fetch, opener=gh.opener)
    return root, gh, updater


@pytest.mark.parametrize("rel, ok", [
    ("strategies/alt.txt", True), ("strategies/hostlists/list-general.txt", True), ("lists/youtube.txt", True),
    ("strategies/assets/tls_clienthello_www_google_com.bin", True),
    ("strategies/hostlists/list-general-user.txt", False), ("strategies/hostlists/ipset-all.txt", False),
    ("strategies/assets/ACTIVE_GAME_UDP.bin", False), ("config.json", False), ("lists/../config.json", False),
    ("lists/sub/x.txt", False), ("Chimera.exe", False), ("lists\\youtube.txt", False),
])
def test_only_data_files_are_published_or_touched(rel, ok):
    assert is_data_path(rel) is ok


def test_newest_data_release_is_found_among_app_releases(env):
    _, gh, updater = env
    gh.publish("2026.10.02", {"strategies/general.txt": b"--b\n"})
    gh.publish("2026.10.04", {"strategies/general.txt": b"--c\n"})
    gh.publish("2026.12.31", {"strategies/general.txt": b"--draft\n"})
    gh.releases[0]["draft"] = True                       # черновик не выпущен, даже если файлы на месте
    info = updater.check()
    assert info["current"] == "2026.10.01" and info["latest"] == "2026.10.04" and info["installable"]
    assert info["plan"]["update"] == ["strategies/general.txt"]


def test_users_own_edits_are_kept_and_shown(env):
    root, gh, updater = env
    (root / "lists" / "youtube.txt").write_bytes(b"youtube.com\nmy-mirror.example\n")
    gh.publish("2026.10.05", {"lists/youtube.txt": b"youtube.com\nyoutu.be\n", "strategies/general.txt": b"--d\n",
                              "lists/new.txt": b"new.example\n"})
    result = updater.install()
    assert result["kept"] == ["lists/youtube.txt"] and result["added"] == ["lists/new.txt"]
    assert result["updated"] == ["strategies/general.txt"]
    assert (root / "lists" / "youtube.txt").read_bytes() == b"youtube.com\nmy-mirror.example\n"
    assert (root / "strategies" / "general.txt").read_bytes() == b"--d\n"
    assert (root / "lists" / "mine.txt").read_bytes() == b"my.example\n"
    assert updater.installed() == "2026.10.05"


def test_a_file_from_an_earlier_data_update_still_counts_as_untouched(env):
    root, gh, updater = env
    gh.publish("2026.10.05", {"strategies/general.txt": b"--d\n"})
    updater.install()
    gh.publish("2026.10.07", {"strategies/general.txt": b"--e\n"})
    assert updater.install()["updated"] == ["strategies/general.txt"]
    assert (root / "strategies" / "general.txt").read_bytes() == b"--e\n"


def test_same_or_older_data_is_not_offered(env):
    _, gh, updater = env
    gh.publish("2026.09.30", {"strategies/general.txt": b"--old\n"})
    info = updater.check()
    assert info["update"] is False and info["installable"] is False
    with pytest.raises(ChimeraError) as e:
        updater.install()
    assert e.value.code == "err.data.nothing"


def test_data_for_a_newer_program_waits_for_the_program_update(env):
    _, gh, updater = env
    gh.publish("2026.10.05", {"strategies/general.txt": b"--d\n"}, min_app="1.2.0")
    info = updater.check()
    assert info["update"] is True and info["installable"] is False and info["min_app"] == "1.2.0"
    with pytest.raises(ChimeraError) as e:
        updater.install()
    assert e.value.code == "err.data.app_too_old"


@pytest.mark.parametrize("extra, tamper", [({"config.json": b"{}"}, None),
                                           ({"../evil.txt": b"x"}, None),
                                           (None, {"strategies/general.txt": b"--evil\n"})])
def test_archive_must_match_the_manifest_exactly(env, extra, tamper):
    root, gh, updater = env
    gh.publish("2026.10.05", {"strategies/general.txt": b"--d\n"}, extra=extra, tamper=tamper)
    with pytest.raises(ChimeraError):
        updater.install()
    assert (root / "strategies" / "general.txt").read_bytes() == b"--a\n" and updater.installed() == "2026.10.01"


def test_downloaded_asset_is_checked_against_its_digest(env):
    root, gh, updater = env
    gh.publish("2026.10.05", {"strategies/general.txt": b"--d\n"})
    url = gh.releases[0]["assets"][0]["browser_download_url"]
    gh.blobs[url] = b"not the archive"
    with pytest.raises(ChimeraError) as e:
        updater.install()
    assert e.value.code == "err.data.checksum" and (root / "strategies" / "general.txt").read_bytes() == b"--a\n"


def test_snapshot_hook_sees_what_will_change_before_any_write(env):
    root, gh, updater = env
    gh.publish("2026.10.05", {"strategies/general.txt": b"--d\n", "lists/new.txt": b"n.example\n"})
    seen = []
    updater.install(before=lambda changed: seen.append((list(changed), (root / "strategies/general.txt").read_bytes())))
    assert seen == [(["lists/new.txt", "strategies/general.txt"], b"--a\n")]


def test_running_from_sources_updates_through_git(env):
    _, gh, updater = env
    updater.frozen = False
    assert updater.check()["error"] == "err.data.source_run"


def test_network_problems_are_reported_not_raised(env):
    _, _, updater = env
    updater.fetch = lambda url: (_ for _ in ()).throw(OSError("offline"))
    assert updater.check()["error"] == "err.data.network"


def test_collect_and_shipped_manifest_cover_only_data(tmp_path):
    root = tmp_path
    (root / "strategies" / "hostlists").mkdir(parents=True)
    (root / "strategies" / "general.txt").write_bytes(b"--a\n")
    (root / "strategies" / "hostlists" / "list-general-user.txt").write_bytes(b"mine\n")
    (root / "config.json").write_bytes(b"{}")
    manifest = dataupdate.write_shipped(root, "2026.10.01")
    assert manifest["files"] == {"strategies/general.txt": h(b"--a\n")}
    assert json.loads((root / "data-manifest.json").read_text(encoding="utf-8"))["version"] == "2026.10.01"


def test_a_file_that_stays_busy_rolls_the_whole_release_back(env, monkeypatch):
    # хостлист держит winws2: половина нового выпуска хуже старого целиком
    from modules.errors import ChimeraPermissionError
    root, gh, updater = env
    gh.publish("2026.10.05", {"strategies/general.txt": b"--d\n", "lists/new.txt": b"new.example\n",
                              "strategies/hostlists/list-general.txt": b"x.example\n"})
    real = dataupdate.atomic_write_bytes

    def busy(path, data, **kwargs):
        if path.name == "list-general.txt":
            raise ChimeraPermissionError("err.file.busy", name=path.name)
        return real(path, data, **kwargs)
    monkeypatch.setattr(dataupdate, "atomic_write_bytes", busy)
    with pytest.raises(ChimeraPermissionError):
        updater.install()
    assert (root / "strategies" / "general.txt").read_bytes() == b"--a\n"
    assert (root / "strategies" / "hostlists" / "list-general.txt").read_bytes() == b"discord.com\n"
    assert not (root / "lists" / "new.txt").exists()
    assert updater.installed() == "2026.10.01"

