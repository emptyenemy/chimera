from pathlib import Path

import pytest

from modules import releasenotes
from tools import release_notes
from ui import updater


ROOT = Path(__file__).resolve().parent.parent


def test_current_release_notes_are_bundled_in_both_languages():
    for lang in ("ru", "en"):
        data = releasenotes.read("1.0.1", lang)
        assert data["version"] == "1.0.1"
        assert "# Chimera 1.0.1" in data["notes"]
        assert "chimera agent-info --json" in data["notes"]
        assert "<!--" not in data["notes"]
    assert "release-notes=release-notes" in (ROOT / "build.bat").read_text()


def test_release_body_uses_exact_bundled_notes_and_portable_checksums():
    body = release_notes.render("v1.0.1", "abc  Chimera-1.0.1-win64.zip\n")
    for lang in ("ru", "en"):
        text = releasenotes.read("1.0.1", lang)["notes"]
        assert f"<!-- chimera:{lang} -->\n{text}\n<!-- /chimera:{lang} -->" in body
    assert "## SHA256" in body and "abc  Chimera-1.0.1-win64.zip" in body


def test_updater_snapshot_has_local_notes_even_when_network_check_fails(monkeypatch):
    monkeypatch.setattr(updater, "VERSION", "1.0.1")
    monkeypatch.setattr(updater.appconfig, "load", lambda: {})
    monkeypatch.setattr(updater.selfupdate, "check", lambda **kwargs: {"error": "offline", "asset": None})
    data = updater.Updater().check()
    assert data["error"] == "offline"
    assert "Chimera 1.0.1" in data["current_release"]["notes"]


@pytest.mark.parametrize("version", ["../../config", "v1", "1.0.1/../../config"])
def test_release_notes_refuse_invalid_version_paths(version):
    assert not releasenotes.read(version)["notes"]
    with pytest.raises(ValueError):
        release_notes.render(version)
