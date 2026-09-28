"""modules/logutil.read_from — инкрементальное чтение + хвост при reset."""

from modules import logutil


def test_missing_file(tmp_path):
    res = logutil.read_from(tmp_path / "no-such.log", offset=0)
    assert res == {"offset": 0, "data": "", "reset": False}


def test_missing_file_nonzero_offset_signals_reset(tmp_path):
    res = logutil.read_from(tmp_path / "no-such.log", offset=100)
    assert res["reset"] is True
    assert res["data"] == ""


def test_first_read_from_zero_returns_whole_small_file(tmp_path):
    p = tmp_path / "a.log"
    # write_bytes — не write_text: на Windows тот бы молча переписал \n в \r\n
    p.write_bytes(b"line1\nline2\n")
    res = logutil.read_from(p, offset=0)
    assert res["reset"] is True
    assert res["data"] == "line1\nline2\n"
    assert res["offset"] == p.stat().st_size


def test_incremental_read_picks_up_only_new_tail(tmp_path):
    p = tmp_path / "a.log"
    p.write_bytes(b"line1\n")
    first = logutil.read_from(p, offset=0)
    with open(p, "ab") as f:
        f.write(b"line2\n")
    second = logutil.read_from(p, offset=first["offset"])
    assert second["reset"] is False
    assert second["data"] == "line2\n"


def test_offset_past_end_of_shrunk_file_triggers_reset(tmp_path):
    p = tmp_path / "a.log"
    p.write_bytes(b"short\n")
    res = logutil.read_from(p, offset=10_000)
    assert res["reset"] is True
    assert res["data"] == "short\n"


def test_ansi_codes_are_stripped(tmp_path):
    p = tmp_path / "a.log"
    p.write_bytes(b"\x1b[36mcolored\x1b[0m text\n")
    res = logutil.read_from(p, offset=0)
    assert res["data"] == "colored text\n"


def test_reset_on_large_file_reads_only_tail_from_line_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(logutil, "_TAIL_BYTES", 100)
    p = tmp_path / "big.log"
    # каждая строка ровно 10 байт ("line0000\n" и т.п.) — удобно считать смещения
    lines = [f"line{i:04d}\n" for i in range(50)]  # 50 * 10 = 500 байт
    p.write_bytes("".join(lines).encode("utf-8"))

    res = logutil.read_from(p, offset=0)
    assert res["reset"] is True
    # не прочитали файл целиком
    assert len(res["data"].encode("utf-8")) <= 100
    # начинается ровно с начала строки, без обрывка
    assert res["data"].startswith("line00")
    assert res["data"] == "".join(lines)[-len(res["data"]):]
    # offset считает от начала РЕАЛЬНОГО файла, а не от начала прочитанного куска
    assert res["offset"] == p.stat().st_size

    # следующий инкрементальный вызов подхватывает только дозапись
    with open(p, "ab") as f:
        f.write(b"line0050\n")
    nxt = logutil.read_from(p, offset=res["offset"])
    assert nxt["reset"] is False
    assert nxt["data"] == "line0050\n"
