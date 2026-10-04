"""Выпуск данных: номер версии, состав архива и что считать изменением."""

import json
import zipfile

from modules import dataupdate
from tools import release_data


def test_version_counts_up_within_a_day_and_is_newer_than_a_build_of_that_day():
    assert release_data.next_version([], today="2026.10.05") == "2026.10.05.1"
    assert release_data.next_version(["2026.10.05.1", "2026.10.05.2", "2026.10.04.7"], today="2026.10.05") == "2026.10.05.3"
    assert dataupdate.version_key("2026.10.05.1") > dataupdate.version_key("2026.10.05")


def test_program_releases_and_data_releases_are_told_apart():
    items = [{"tagName": "v1.0.3"}, {"tagName": "v1.1.0"}, {"tagName": "v1.2.0-beta.1", "isPrerelease": True},
             {"tagName": "data-2026.10.05.1"}, {"tagName": "data-2026.10.06.1"}, {"tagName": "data-junk"}]
    assert release_data.latest_app(items) == "1.1.0"
    assert release_data.published_data(items) == ["2026.10.06.1", "2026.10.05.1"]


def test_archive_holds_exactly_the_manifest_and_is_reproducible(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "lists").mkdir(parents=True)
    (root / "strategies" / "hostlists").mkdir(parents=True)
    (root / "lists" / "youtube.txt").write_bytes(b"youtube.com\n")
    (root / "strategies" / "general.txt").write_bytes(b"--a\n")
    (root / "strategies" / "hostlists" / "list-general-user.txt").write_bytes(b"mine\n")
    monkeypatch.setattr(release_data, "ROOT", root)
    monkeypatch.setattr(dataupdate, "collect", lambda _root, real=dataupdate.collect: real(root))
    manifest, archive, manifest_path = release_data.build("2026.10.05.1", "1.1.0", tmp_path / "a")
    with zipfile.ZipFile(archive) as z:
        assert sorted(z.namelist()) == sorted(manifest["files"]) == ["lists/youtube.txt", "strategies/general.txt"]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["min_app"] == "1.1.0"
    _, again, _ = release_data.build("2026.10.05.1", "1.1.0", tmp_path / "b")
    assert archive.read_bytes() == again.read_bytes()


def test_changes_are_split_into_added_changed_and_removed():
    assert release_data.diff({"a": "1", "b": "2"}, {"b": "3", "c": "4"}) == {"added": ["c"], "changed": ["b"], "removed": ["a"]}
