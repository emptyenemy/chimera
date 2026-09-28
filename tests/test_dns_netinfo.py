"""modules/dns_jumper/netinfo.py — замена PowerShell-опроса адаптеров на
GetAdaptersAddresses (ctypes). Модуль дёргает ctypes.windll на импорте —
собрать/проверить его можно только на Windows.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="ctypes.windll — только Windows")

from modules.dns_jumper import netinfo  # noqa: E402 - после skipif


# --- чистая логика форматирования (без обращений к системе) -------------------


@pytest.mark.parametrize("bps,expected", [
    (1_000_000_000, "1 Gbps"),
    (1_215_752_192, "1.2 Gbps"),
    (100_000_000_000, "100 Gbps"),
    (10_000_000_000, "10 Gbps"),
    (100_000_000, "100 Mbps"),
    (54_000_000, "54 Mbps"),
    (56_000, "56 Kbps"),
    (500, "500 bps"),
])
def test_format_speed(bps, expected):
    assert netinfo._format_speed(bps) == expected


def test_mac_str_formats_dash_separated_uppercase_hex():
    raw = bytes([0x04, 0x7C, 0x16, 0x49, 0x4C, 0xC5, 0xFF, 0xFF])
    assert netinfo._mac_str(raw, 6) == "04-7C-16-49-4C-C5"


def test_mac_str_empty_when_length_zero():
    assert netinfo._mac_str(bytes(8), 0) == ""


# --- живой опрос системы: только форма ответа, без сравнения с PowerShell -----
# (сверка байт-в-байт со старой PS-реализацией на реальном железе делалась
# вручную при разработке — PowerShell-путь секунды, гонять его в каждом
# прогоне тестов не стоит; здесь проверяем контракт формата и то, что не падает).


def test_adapters_returns_expected_shape():
    result = netinfo.adapters()
    assert isinstance(result, list)
    for a in result:
        assert set(a) == {"index", "name", "desc", "status", "physical", "mac", "speed", "ipv4", "dns"}
        assert isinstance(a["index"], int)
        assert isinstance(a["name"], str)
        assert isinstance(a["status"], str)
        assert isinstance(a["physical"], bool)
        assert isinstance(a["ipv4"], list)
        assert isinstance(a["dns"], list)
        assert all(isinstance(ip, str) for ip in a["ipv4"])
        assert all(isinstance(ip, str) for ip in a["dns"])


def test_adapters_excludes_software_loopback_pseudo_interface():
    # Get-NetAdapter никогда не показывает "Loopback Pseudo-Interface 1" —
    # наш путь должен так же его выкидывать (IfType 24)
    names = [a["name"] for a in netinfo.adapters()]
    assert not any("loopback pseudo-interface" in n.lower() for n in names)


def test_adapters_sorted_up_first_then_physical_then_name():
    result = netinfo.adapters()
    keys = [(a["status"] != "Up", not a["physical"], a["name"]) for a in result]
    assert keys == sorted(keys)
