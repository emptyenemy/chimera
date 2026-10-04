"""modules/blockcheck.py — разбор ответа: статус, отказ сайта, челлендж и заморозка посреди тела."""

import ssl

import pytest

from modules import blockcheck

OK_HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"


class Tls:
    """Поддельное TLS-соединение: отдаёт заготовленные куски, потом — конец или исключение."""

    def __init__(self, chunks, end=b""):
        self.chunks, self.end = list(chunks), end
        self.sent, self.timeout = b"", None

    def recv(self, n):
        if self.chunks:
            return self.chunks.pop(0)
        if isinstance(self.end, BaseException):
            raise self.end
        return self.end

    def sendall(self, data):
        self.sent += data

    def settimeout(self, value):
        self.timeout = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def serve(monkeypatch):
    def run(chunks, end=b""):
        tls = Tls(chunks, end)
        monkeypatch.setattr(blockcheck, "_ssl_ctx", type("Ctx", (), {"wrap_socket": lambda self, sock, server_hostname: tls})())
        return blockcheck._classify(None, "site.example"), tls
    return run


def test_a_whole_page_is_ok_and_the_request_asks_for_the_body(serve):
    (status, _), tls = serve([OK_HEAD + b"<html>", b"x" * 30000])
    assert status == "ok"
    assert tls.sent.startswith(b"GET / HTTP/1.1\r\nHost: site.example\r\n") and b"Connection: close" in tls.sent


def test_a_transfer_that_freezes_after_16_kb_is_a_block(serve):
    (status, reason), tls = serve([OK_HEAD, b"x" * 8192, b"x" * 8192], end=TimeoutError())
    assert status == "fail" and "16" in reason
    assert tls.timeout == blockcheck.STALL_TIMEOUT


def test_a_reset_in_the_middle_of_the_body_is_a_block(serve):
    (status, _), _ = serve([OK_HEAD, b"x" * 9000], end=ConnectionResetError())
    assert status == "fail"


def test_closing_without_close_notify_is_a_normal_end(serve):
    (status, _), _ = serve([OK_HEAD, b"x" * 9000], end=ssl.SSLEOFError())
    assert status == "ok"


@pytest.mark.parametrize("head,chunks", [
    (b"HTTP/1.1 301 Moved\r\nLocation: https://www.site.example/\r\nContent-Length: 0\r\n\r\n", []),
    (b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n12345", [b"67890"]),
    (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n", [b"0\r\n\r\n"]),
])
def test_a_complete_response_does_not_wait_for_the_server_to_close(serve, head, chunks):
    # сервер держит соединение открытым: лишнее чтение упёрлось бы в таймаут и дало бы ложную блокировку
    (status, _), _ = serve([head, *chunks], end=TimeoutError())
    assert status == "ok"


def test_the_probe_stops_at_its_limit_on_a_big_page(serve):
    (status, _), tls = serve([OK_HEAD] + [b"x" * 16384] * 4, end=TimeoutError())
    assert status == "ok" and tls.chunks == []


@pytest.mark.parametrize("head,expected", [
    (b"HTTP/1.1 403 Forbidden\r\n\r\n", ("denied", 403)),
    (b"HTTP/1.1 403 Forbidden\r\ncf-mitigated: challenge\r\n\r\n", ("challenge", 403)),
    (b"SSH-2.0-OpenSSH\r\n\r\n", ("fail", None)),
])
def test_refusals_challenges_and_garbage_are_told_apart(serve, head, expected):
    (status, detail), _ = serve([head], end=TimeoutError())
    assert status == expected[0] and (expected[1] is None or detail == expected[1])
