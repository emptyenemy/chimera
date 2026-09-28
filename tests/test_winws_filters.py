"""modules/winws/filters.py — game-фильтр (off/all/tcp/udp) и
modules/winws/manager.py::WinwsManager._apply_game_filter — подстановка
плейсхолдеров в аргументы winws2. appconfig подменяется monkeypatch'ем,
реальный config.json не трогаем; ipset/fake-slot логика тут не нужна.
"""

import pytest

from modules import appconfig
from modules.winws import filters
from modules.winws.manager import WinwsManager


@pytest.fixture
def fake_config(monkeypatch):
    """appconfig.load()/set_value() работают с словарём в памяти вместо
    реального config.json — и filters.py, и manager.py читают его через
    `from modules import appconfig`, поэтому патчим сам модуль appconfig."""
    store = {}

    def _load():
        return dict(appconfig.DEFAULTS, **store)

    def _set_value(key, value):
        store[key] = value
        return _load()

    monkeypatch.setattr(appconfig, "load", _load)
    monkeypatch.setattr(appconfig, "set_value", _set_value)
    return store


# --- filters.game_mode / set_game_mode / game_ports ----------------------------


def test_game_mode_default_off(fake_config):
    assert filters.game_mode() == "off"


def test_game_mode_invalid_value_in_config_falls_back_to_off(fake_config):
    fake_config["game_filter"] = "bogus"
    assert filters.game_mode() == "off"


@pytest.mark.parametrize("mode", ["off", "all", "tcp", "udp"])
def test_set_game_mode_roundtrip(fake_config, mode):
    assert filters.set_game_mode(mode) == mode
    assert filters.game_mode() == mode


def test_set_game_mode_rejects_invalid():
    with pytest.raises(ValueError):
        filters.set_game_mode("bogus")


def test_game_ports_off_is_none(fake_config):
    fake_config["game_filter"] = "off"
    assert filters.game_ports() is None


def test_game_ports_all_both_ranges(fake_config):
    fake_config["game_filter"] = "all"
    assert filters.game_ports() == {"tcp": "1024-65535", "udp": "1024-65535"}


def test_game_ports_tcp_only(fake_config):
    fake_config["game_filter"] = "tcp"
    assert filters.game_ports() == {"tcp": "1024-65535", "udp": None}


def test_game_ports_udp_only(fake_config):
    fake_config["game_filter"] = "udp"
    assert filters.game_ports() == {"tcp": None, "udp": "1024-65535"}


def test_game_ports_explicit_mode_overrides_config(fake_config):
    fake_config["game_filter"] = "off"
    assert filters.game_ports("all") == {"tcp": "1024-65535", "udp": "1024-65535"}


# --- filters.validate_game_range ------------------------------------------------


@pytest.mark.parametrize("value", [
    "1024-65535",
    "80",
    "65535",
    "1",
    "1024-1934,1936-65535",
    "  1024 - 65535 ",  # пробелы вырезаются целиком, как у Flowseal
])
def test_validate_game_range_accepts_valid(value):
    assert filters.validate_game_range(value) == "".join(value.split())


@pytest.mark.parametrize("value", [
    "",
    "   ",
    "0",
    "0-100",
    "01-100",           # ведущий ноль
    "100-50",           # начало больше конца
    "1024-70000",       # конец за пределами 65535
    "700000",           # больше 5 цифр
    "80-",
    "-80",
    "abc",
    "80,",
])
def test_validate_game_range_rejects_invalid(value):
    with pytest.raises(ValueError):
        filters.validate_game_range(value)


# --- filters.game_ranges / set_game_ranges --------------------------------------


def test_game_ranges_default(fake_config):
    assert filters.game_ranges() == {"tcp": "1024-65535", "udp": "1024-65535"}


def test_game_ranges_falls_back_on_bogus_stored_value(fake_config):
    fake_config["game_filter_tcp"] = "not-a-range"
    assert filters.game_ranges()["tcp"] == "1024-65535"


def test_set_game_ranges_roundtrip(fake_config):
    result = filters.set_game_ranges(tcp="2000-3000", udp="4000-5000")
    assert result == {"tcp": "2000-3000", "udp": "4000-5000"}
    assert filters.game_ranges() == {"tcp": "2000-3000", "udp": "4000-5000"}


def test_set_game_ranges_partial_update_keeps_other_side(fake_config):
    filters.set_game_ranges(tcp="2000-3000", udp="4000-5000")
    filters.set_game_ranges(tcp="9000-9999")
    assert filters.game_ranges() == {"tcp": "9000-9999", "udp": "4000-5000"}


def test_set_game_ranges_rejects_invalid():
    with pytest.raises(ValueError):
        filters.set_game_ranges(tcp="bogus")


def test_game_ports_uses_configured_ranges(fake_config):
    filters.set_game_ranges(tcp="2000-3000", udp="4000-5000")
    fake_config["game_filter"] = "all"
    assert filters.game_ports() == {"tcp": "2000-3000", "udp": "4000-5000"}


# --- WinwsManager._apply_game_filter ------------------------------------------


def _lines_with_game_profiles():
    return [
        "--wf-tcp-out=80,443{GAME_TCP_WF}",
        "--wf-udp-out=443{GAME_UDP_WF}",
        "--filter-tcp=80,443",
        "--lua-desync=fake:blob=tls_google",
        "--new",
        "--filter-tcp={GAME_TCP}",
        "--lua-desync=fake:blob=tls_google",
        "--new",
        "--filter-udp={GAME_UDP}",
        "--lua-desync=fake:blob=quic_google",
    ]


def test_apply_game_filter_off_drops_game_blocks_and_placeholders(fake_config):
    fake_config["game_filter"] = "off"
    out = WinwsManager._apply_game_filter(_lines_with_game_profiles())
    text = "\n".join(out)
    assert "{GAME_TCP}" not in text
    assert "{GAME_UDP}" not in text
    assert "{GAME_TCP_WF}" not in text
    assert "{GAME_UDP_WF}" not in text
    # оба игровых блока целиком выкинуты — остаётся только первый (не-игровой)
    assert out.count("--new") == 0
    assert "--filter-tcp=80,443" in out


def test_apply_game_filter_all_keeps_both_blocks_with_ports(fake_config):
    fake_config["game_filter"] = "all"
    out = WinwsManager._apply_game_filter(_lines_with_game_profiles())
    text = "\n".join(out)
    assert "--wf-tcp-out=80,443,1024-65535" in text
    assert "--wf-udp-out=443,1024-65535" in text
    assert "--filter-tcp=1024-65535" in out
    assert "--filter-udp=1024-65535" in out
    assert out.count("--new") == 2  # все три блока сохранены


def test_apply_game_filter_tcp_only_drops_udp_block(fake_config):
    fake_config["game_filter"] = "tcp"
    out = WinwsManager._apply_game_filter(_lines_with_game_profiles())
    text = "\n".join(out)
    assert "--filter-tcp=1024-65535" in out
    assert "{GAME_UDP}" not in text
    assert "--filter-udp=1024-65535" not in out
    assert out[1] == "--wf-udp-out=443"  # без игрового диапазона (режим tcp)
    assert out.count("--new") == 1  # общий блок + game-tcp, udp-блок выкинут


def test_apply_game_filter_udp_only_drops_tcp_block(fake_config):
    fake_config["game_filter"] = "udp"
    out = WinwsManager._apply_game_filter(_lines_with_game_profiles())
    text = "\n".join(out)
    assert "--filter-udp=1024-65535" in out
    assert "{GAME_TCP}" not in text
    assert "--filter-tcp=1024-65535" not in out
    assert out[0] == "--wf-tcp-out=80,443"
    assert out.count("--new") == 1  # общий блок + game-udp, tcp-блок выкинут


def test_apply_game_filter_non_game_lines_untouched(fake_config):
    fake_config["game_filter"] = "off"
    lines = ["--filter-tcp=80,443", "--lua-desync=fake:blob=tls_google"]
    assert WinwsManager._apply_game_filter(lines) == lines


def test_apply_game_filter_uses_configured_custom_ranges(fake_config):
    fake_config["game_filter"] = "all"
    filters.set_game_ranges(tcp="2000-3000", udp="4000-5000")
    out = WinwsManager._apply_game_filter(_lines_with_game_profiles())
    text = "\n".join(out)
    assert "--wf-tcp-out=80,443,2000-3000" in text
    assert "--wf-udp-out=443,4000-5000" in text
    assert "--filter-tcp=2000-3000" in out
    assert "--filter-udp=4000-5000" in out
    assert "1024-65535" not in text
