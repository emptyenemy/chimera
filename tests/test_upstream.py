"""modules/upstream.py — сравнение версий (_key) и выбор последнего тега
(_latest_tag) с замоканным _git (без сети и без реального git-процесса)."""

from types import SimpleNamespace

import pytest

from modules import upstream


# --- _key: натуральное сравнение версий ---------------------------------------


@pytest.mark.parametrize("lower,higher", [
    ("1.9.9", "1.9.10"),        # числа сравниваются как числа, не лексикографически
    ("1.9.9", "1.9.9c"),        # буквенный суффикс > голого номера
    ("1.9.9b", "1.9.9c"),
    ("v1.0.0", "v1.0.1"),
    ("1.9.2", "1.10.0"),
])
def test_key_orders_versions(lower, higher):
    assert upstream._key(lower) < upstream._key(higher)


def test_current_in_build_reads_versions_json(tmp_path, monkeypatch):
    # в собранной программе git нет — версии сабмодулей пишутся при сборке в versions.json
    vf = tmp_path / "versions.json"
    vf.write_text('{"Движок zapret2 (winws2)": "v1.0.5.2", "winws-бандл (bol-van)": "6eb463a"}',
                  encoding="utf-8")
    monkeypatch.setattr(upstream.paths, "IS_FROZEN", True)
    monkeypatch.setattr(upstream, "VERSIONS_FILE", vf)
    assert upstream._current(upstream._source("Движок zapret2 (winws2)")) == "v1.0.5.2"
    assert upstream._current(upstream._source("winws-бандл (bol-van)")) == "6eb463a"
    assert upstream._current(upstream._source("TG-прокси (Flowseal)")) == "—"  # нет в файле


def test_current_in_build_without_versions_json(tmp_path, monkeypatch):
    monkeypatch.setattr(upstream.paths, "IS_FROZEN", True)
    monkeypatch.setattr(upstream, "VERSIONS_FILE", tmp_path / "missing.json")
    assert upstream._current(upstream._source("Движок zapret2 (winws2)")) == "—"


def test_key_v_prefix_equal_to_bare_version():
    assert upstream._key("v1.9.9") == upstream._key("1.9.9")


def test_key_equal_versions_are_equal():
    assert upstream._key("1.9.9") == upstream._key("1.9.9")


def test_key_case_insensitive_letter_suffix():
    assert upstream._key("1.9.9C") == upstream._key("1.9.9c")


# --- _latest_tag: сортировка тегов + отсечение пре-релизов --------------------


def _fake_git_ok(stdout: str):
    def _git(args, cwd=None, timeout=15):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return _git


def test_latest_tag_picks_highest_natural_version(monkeypatch):
    stdout = (
        "abc123\trefs/tags/1.9.2\n"
        "def456\trefs/tags/1.9.10\n"
        "aaa111\trefs/tags/1.9.9\n"
    )
    monkeypatch.setattr(upstream, "_git", _fake_git_ok(stdout))
    assert upstream._latest_tag("https://example.invalid/repo.git") == "1.9.10"


def test_latest_tag_excludes_prereleases_with_dash(monkeypatch):
    """Пре-релизы (с дефисом, alpha/beta/rc) отсекаются — важно для sing-box,
    у которого теги вида v1.14.0-beta.1 не должны считаться latest."""
    stdout = (
        "abc\trefs/tags/1.14.2\n"
        "def\trefs/tags/1.15.0-beta.1\n"
        "ghi\trefs/tags/1.15.0-rc1\n"
    )
    monkeypatch.setattr(upstream, "_git", _fake_git_ok(stdout))
    assert upstream._latest_tag("https://example.invalid/repo.git") == "1.14.2"


def test_latest_tag_no_network_returns_none(monkeypatch):
    monkeypatch.setattr(upstream, "_git", lambda *a, **kw: None)
    assert upstream._latest_tag("https://example.invalid/repo.git") is None


def test_latest_tag_git_nonzero_returncode_returns_none(monkeypatch):
    monkeypatch.setattr(
        upstream, "_git",
        lambda *a, **kw: SimpleNamespace(returncode=128, stdout="", stderr="fatal"),
    )
    assert upstream._latest_tag("https://example.invalid/repo.git") is None


def test_latest_tag_no_tags_returns_none(monkeypatch):
    monkeypatch.setattr(upstream, "_git", _fake_git_ok(""))
    assert upstream._latest_tag("https://example.invalid/repo.git") is None


def test_latest_tag_all_prerelease_returns_none(monkeypatch):
    stdout = "abc\trefs/tags/1.0.0-alpha\n"
    monkeypatch.setattr(upstream, "_git", _fake_git_ok(stdout))
    assert upstream._latest_tag("https://example.invalid/repo.git") is None
