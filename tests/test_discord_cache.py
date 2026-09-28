"""modules/discord.py — очистка кэша Discord на временной структуре папок
(monkeypatch APPDATA нам не нужен: clear_cache принимает appdata параметром).
Ничего реального не удаляется, tasklist/pids_by_name подменяются running_check."""

import pytest

from modules import discord as discord_cache


def _make_variant(base, dirname, with_cache=True):
    root = base / dirname
    root.mkdir(parents=True, exist_ok=True)
    if with_cache:
        for sub in ("Cache", "Code Cache", "GPUCache"):
            d = root / sub
            d.mkdir()
            (d / "data.bin").write_bytes(b"x" * 100)
    return root


def test_no_discord_found_returns_empty_note(tmp_path):
    res = discord_cache.clear_cache(appdata=tmp_path, running_check=lambda names: set())
    assert res == {"cleared": [], "freed_bytes": 0, "note": "установленный Discord не найден"}


def test_clears_cache_dirs_and_reports_freed_bytes(tmp_path):
    _make_variant(tmp_path, "discord")
    res = discord_cache.clear_cache(appdata=tmp_path, running_check=lambda names: set())
    assert res["freed_bytes"] == 300  # 3 подпапки по 100 байт
    assert len(res["cleared"]) == 1
    entry = res["cleared"][0]
    assert entry["name"] == "Discord"
    assert set(entry["cleared_dirs"]) == {"Cache", "Code Cache", "GPUCache"}
    assert not (tmp_path / "discord" / "Cache").exists()
    assert not (tmp_path / "discord" / "Code Cache").exists()
    assert not (tmp_path / "discord" / "GPUCache").exists()


def test_clears_multiple_variants(tmp_path):
    _make_variant(tmp_path, "discord")
    _make_variant(tmp_path, "discordptb")
    res = discord_cache.clear_cache(appdata=tmp_path, running_check=lambda names: set())
    names = {c["name"] for c in res["cleared"]}
    assert names == {"Discord", "Discord PTB"}
    assert res["freed_bytes"] == 600


def test_raises_when_discord_running_and_does_not_delete(tmp_path):
    _make_variant(tmp_path, "discord")
    with pytest.raises(RuntimeError, match="Discord"):
        discord_cache.clear_cache(appdata=tmp_path, running_check=lambda names: {"Discord.exe"})
    # ничего не удалено — процесс был "запущен"
    assert (tmp_path / "discord" / "Cache").exists()


def test_running_check_receives_only_found_variant_exes(tmp_path):
    _make_variant(tmp_path, "discord")
    seen = {}

    def fake_check(names):
        seen["names"] = names
        return set()

    discord_cache.clear_cache(appdata=tmp_path, running_check=fake_check)
    assert seen["names"] == ["Discord.exe"]


def test_missing_cache_subdir_is_skipped_without_error(tmp_path):
    root = tmp_path / "discord"
    root.mkdir()
    (root / "Cache").mkdir()
    (root / "Cache" / "f.bin").write_bytes(b"abc")
    # Code Cache/GPUCache отсутствуют — не должно падать
    res = discord_cache.clear_cache(appdata=tmp_path, running_check=lambda names: set())
    assert res["cleared"][0]["cleared_dirs"] == ["Cache"]
    assert res["freed_bytes"] == 3


def test_appdata_env_missing_raises(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    with pytest.raises(RuntimeError):
        discord_cache._appdata()
