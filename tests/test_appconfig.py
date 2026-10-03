"""Settings batches are validated and serialized before replacing the config file."""

import json
import threading

import pytest

from modules import appconfig


@pytest.mark.parametrize("patch", [
    {"theme": "light", "lang": "invalid"},
    {"theme": "light", "unknown": True},
    {"close_to_tray": False, "theme": "invalid"},
    {"close_to_tray": False, "appearance": {"bogus": 1}},
])
def test_invalid_batch_preserves_file_and_does_not_refresh_language(monkeypatch, patch):
    before = b'{"theme":"dark","lang":"ru"}\r\n'
    appconfig.CONFIG_PATH.write_bytes(before)
    refreshed = []
    monkeypatch.setattr(appconfig.i18n, "refresh", lambda: refreshed.append(1))
    with pytest.raises(ValueError):
        appconfig.set_values(patch)
    assert appconfig.CONFIG_PATH.read_bytes() == before
    assert refreshed == []


def test_valid_batch_writes_once_and_refreshes_language_after_commit(monkeypatch):
    appconfig.CONFIG_PATH.write_bytes(b'{"theme":"dark","unrelated":"preserved"}')
    writes, refreshed = [], []
    real_write = appconfig._write

    def write(data):
        writes.append(dict(data))
        real_write(data)

    monkeypatch.setattr(appconfig, "_write", write)
    monkeypatch.setattr(appconfig.i18n, "refresh", lambda: refreshed.append(json.loads(appconfig.CONFIG_PATH.read_text())))
    result = appconfig.set_values({"theme": "light", "lang": "en"})
    assert len(writes) == len(refreshed) == 1
    assert result == refreshed[0]
    assert result["theme"] == "light" and result["lang"] == "en"
    assert result["unrelated"] == "preserved"


def test_failed_batch_preserves_file_and_does_not_refresh_language(monkeypatch):
    before = b'{"theme":"dark","lang":"ru"}'
    appconfig.CONFIG_PATH.write_bytes(before)
    refreshed = []

    def fail(*args, **kwargs):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr(appconfig, "atomic_write_text", fail)
    monkeypatch.setattr(appconfig.i18n, "refresh", lambda: refreshed.append(1))
    with pytest.raises(OSError):
        appconfig.set_values({"theme": "light", "lang": "en"})
    assert appconfig.CONFIG_PATH.read_bytes() == before
    assert refreshed == []


def test_empty_batch_only_reads(monkeypatch):
    monkeypatch.setattr(appconfig, "_write", lambda data: pytest.fail("An empty batch must not write"))
    assert appconfig.set_values({}) == appconfig.load()
    assert not appconfig.CONFIG_PATH.exists()


def test_concurrent_single_setting_saves_preserve_both_changes(monkeypatch):
    appconfig.CONFIG_PATH.write_bytes(b'{"theme":"dark","close_to_tray":true}')
    ready, release, started, second_read = (threading.Event() for _ in range(4))
    real_write, real_load = appconfig._write, appconfig.load
    errors = []

    def write(data):
        if threading.current_thread().name == "theme-save":
            ready.set()
            assert release.wait(3)
        real_write(data)

    def load():
        data = real_load()
        if threading.current_thread().name == "tray-save":
            second_read.set()
        return data

    monkeypatch.setattr(appconfig, "_write", write)
    monkeypatch.setattr(appconfig, "load", load)

    def save(key, value):
        try:
            if key == "close_to_tray":
                started.set()
            appconfig.set_value(key, value)
        except Exception as error:
            errors.append(error)

    first = threading.Thread(target=save, args=("theme", "light"), name="theme-save")
    second = threading.Thread(target=save, args=("close_to_tray", False), name="tray-save")
    first.start()
    try:
        assert ready.wait(2)
        second.start()
        assert started.wait(2)
        second_read.wait(0.2)
    finally:
        release.set()
        first.join(timeout=3)
        if second.ident is not None:
            second.join(timeout=3)
    assert not first.is_alive() and not second.is_alive() and not errors
    result = appconfig.load()
    assert result["theme"] == "light" and result["close_to_tray"] is False
