"""modules/hosts/static_providers.py — парсинг hosts-формата и обвязка
провайдера Flowseal (available=False без падений, если файла сабмодуля нет)."""

import pytest

from modules.hosts import static_providers


# --- parse_hosts_text ---------------------------------------------------------


def test_parse_hosts_text_basic_line():
    entries = static_providers.parse_hosts_text("1.2.3.4 example.com\n")
    assert entries == [{"ip": "1.2.3.4", "host": "example.com"}]


def test_parse_hosts_text_skips_comments_and_blank_lines():
    text = "# заголовок\n\n1.2.3.4 example.com\n# ещё коммент\n"
    assert static_providers.parse_hosts_text(text) == [{"ip": "1.2.3.4", "host": "example.com"}]


def test_parse_hosts_text_trailing_comment_on_line():
    entries = static_providers.parse_hosts_text("1.2.3.4 example.com # почему тут этот адрес\n")
    assert entries == [{"ip": "1.2.3.4", "host": "example.com"}]


def test_parse_hosts_text_multiple_hosts_per_ip():
    entries = static_providers.parse_hosts_text("1.2.3.4 a.example b.example c.example\n")
    assert entries == [
        {"ip": "1.2.3.4", "host": "a.example"},
        {"ip": "1.2.3.4", "host": "b.example"},
        {"ip": "1.2.3.4", "host": "c.example"},
    ]


def test_parse_hosts_text_same_host_multiple_ips_not_deduped():
    """Flowseal раздаёt discord.com сразу на несколько CDN-адресов — все записи нужны."""
    text = "1.1.1.1 discord.com\n2.2.2.2 discord.com\n"
    entries = static_providers.parse_hosts_text(text)
    assert entries == [
        {"ip": "1.1.1.1", "host": "discord.com"},
        {"ip": "2.2.2.2", "host": "discord.com"},
    ]


def test_parse_hosts_text_ignores_malformed_line():
    entries = static_providers.parse_hosts_text("justonetoken\n1.2.3.4 ok.example\n")
    assert entries == [{"ip": "1.2.3.4", "host": "ok.example"}]


def test_parse_hosts_text_ipv6_line():
    entries = static_providers.parse_hosts_text("2606:50c0:8000::154 raw.githubusercontent.com\n")
    assert entries == [{"ip": "2606:50c0:8000::154", "host": "raw.githubusercontent.com"}]


# --- providers()/get()/read_entries() -----------------------------------------


def test_providers_lists_flowseal_with_type_static():
    items = static_providers.providers()
    assert any(p["id"] == "flowseal-hosts" and p["type"] == "static" for p in items)


def test_providers_marks_unavailable_when_file_missing(monkeypatch, tmp_path):
    missing = tmp_path / "nope" / "hosts"
    monkeypatch.setitem(static_providers._STATIC[0], "path", missing)
    items = static_providers.providers()
    flowseal = next(p for p in items if p["id"] == "flowseal-hosts")
    assert flowseal["available"] is False
    assert flowseal["reason"]  # причина не пустая


def test_get_unknown_id_raises_keyerror():
    with pytest.raises(KeyError):
        static_providers.get("no-such-provider")


def test_read_entries_missing_file_raises_filenotfound(monkeypatch, tmp_path):
    missing = tmp_path / "nope" / "hosts"
    monkeypatch.setitem(static_providers._STATIC[0], "path", missing)
    with pytest.raises(FileNotFoundError):
        static_providers.read_entries("flowseal-hosts")


def test_read_entries_reads_and_parses_file(monkeypatch, tmp_path):
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("9.9.9.9 example.org\n", encoding="utf-8")
    monkeypatch.setitem(static_providers._STATIC[0], "path", hosts_file)
    assert static_providers.read_entries("flowseal-hosts") == [{"ip": "9.9.9.9", "host": "example.org"}]


def test_read_entries_rereads_file_each_call(monkeypatch, tmp_path):
    """Обновление сабмодуля должно подхватываться без правок кода — читаем заново каждый раз."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("1.1.1.1 first.example\n", encoding="utf-8")
    monkeypatch.setitem(static_providers._STATIC[0], "path", hosts_file)
    assert static_providers.read_entries("flowseal-hosts")[0]["ip"] == "1.1.1.1"

    hosts_file.write_text("2.2.2.2 first.example\n", encoding="utf-8")
    assert static_providers.read_entries("flowseal-hosts")[0]["ip"] == "2.2.2.2"
