"""Mode and port ranges are committed together before a running engine is restarted."""

import json
from contextlib import nullcontext

import pytest

from modules import appconfig
from modules.winws import filters
from ui import api as api_mod


@pytest.fixture
def game_config(monkeypatch):
    before = {"theme": "dark", "close_to_tray": False, "game_filter": "tcp",
              "game_filter_tcp": "2000-3000", "game_filter_udp": "4000-5000"}
    appconfig.CONFIG_PATH.write_bytes(json.dumps(before).encode())
    calls = []
    instance = api_mod.Api.__new__(api_mod.Api)
    monkeypatch.setattr(api_mod.configbackups, "automatic", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(api_mod.service, "is_running", lambda: False)
    monkeypatch.setattr(instance, "_restart_winws_if_running", lambda: calls.append(appconfig.load()))
    monkeypatch.setattr(filters, "state", lambda: {"game": filters.game_mode(), "game_ranges": filters.game_ranges()})
    return instance, calls


@pytest.mark.parametrize("mode,tcp,udp", [
    ("all", "9000-9999", "invalid"), ("udp", "9000", "70000"),
    ("off", None, ""), ("all", "100-50", "9000"), ("bogus", "9000", "9100"),
])
def test_invalid_filter_request_preserves_every_setting_and_does_not_restart(game_config, mode, tcp, udp):
    instance, calls = game_config
    before = appconfig.CONFIG_PATH.read_bytes()
    result = instance.game_filter_set(mode, tcp, udp)
    assert result["ok"] is False
    assert appconfig.CONFIG_PATH.read_bytes() == before
    assert calls == []


def test_invalid_second_range_does_not_save_first_range(game_config):
    before = appconfig.CONFIG_PATH.read_bytes()
    with pytest.raises(ValueError):
        filters.set_game_ranges("9000-9999", "invalid")
    assert appconfig.CONFIG_PATH.read_bytes() == before


@pytest.mark.parametrize("tcp,udp", [("9000-9999", "9100"), (None, "9100"), (None, None)])
def test_filter_request_writes_once_and_restarts_with_complete_settings(game_config, monkeypatch, tcp, udp):
    instance, calls = game_config
    writes = []
    real_write = appconfig._write

    def write(data):
        writes.append(dict(data))
        real_write(data)

    monkeypatch.setattr(appconfig, "_write", write)
    result = instance.game_filter_set("all", tcp, udp)
    assert result["ok"] is True
    assert len(writes) == len(calls) == 1
    confirmed = calls[0]
    assert confirmed["game_filter"] == "all"
    assert confirmed["game_filter_tcp"] == (tcp if tcp is not None else "2000-3000")
    assert confirmed["game_filter_udp"] == (udp if udp is not None else "4000-5000")
    assert confirmed["theme"] == "dark" and confirmed["close_to_tray"] is False
    assert result["data"]["game_ranges"] == {"tcp": confirmed["game_filter_tcp"], "udp": confirmed["game_filter_udp"]}


def test_failed_filter_commit_preserves_all_settings_and_does_not_restart(game_config, monkeypatch):
    instance, calls = game_config
    before = appconfig.CONFIG_PATH.read_bytes()
    real_write = appconfig._write
    writes = []

    def write(data):
        writes.append(dict(data))
        if len(writes) > 1 or "game_filter_tcp" in data and data["game_filter_tcp"] == "9000":
            raise OSError("Simulated disk failure")
        real_write(data)

    monkeypatch.setattr(appconfig, "_write", write)
    result = instance.game_filter_set("all", "9000", "9100")
    assert result["ok"] is False
    assert appconfig.CONFIG_PATH.read_bytes() == before
    assert calls == []


def test_failed_restart_reports_error_without_undoing_complete_commit(game_config, monkeypatch):
    instance, _ = game_config

    def restart():
        raise RuntimeError("Simulated restart failure")

    monkeypatch.setattr(instance, "_restart_winws_if_running", restart)
    result = instance.game_filter_set("all", "9000", "9100")
    assert result["ok"] is True
    assert result["data"]["apply_error"] == "Simulated restart failure"
    assert appconfig.load()["game_filter"] == "all"
    assert filters.game_ranges() == {"tcp": "9000", "udp": "9100"}


@pytest.mark.parametrize("read", ["ranges", "ports", "state"])
def test_game_reads_do_not_mix_two_successive_configurations(monkeypatch, read):
    before = {"game_filter": "all", "game_filter_tcp": "80", "game_filter_udp": "90"}
    after = {"game_filter": "off", "game_filter_tcp": "9000", "game_filter_udp": "9100"}
    snapshots = [before, after, after]

    def load():
        return snapshots.pop(0)

    monkeypatch.setattr(appconfig, "load", load)
    if read == "ranges":
        result = filters.game_ranges()
    elif read == "ports":
        result = filters.game_ports()
    else:
        monkeypatch.setattr(filters, "ipset_state", lambda: "none")
        monkeypatch.setattr(filters, "ipset_count", lambda: 0)
        monkeypatch.setattr(filters, "ipset_stored", lambda: 0)
        monkeypatch.setattr(filters, "fakes_state", lambda: {})
        state = filters.state()
        assert state["game"] == "all"
        result = state["game_ranges"]
    assert result == {"tcp": "80", "udp": "90"}
