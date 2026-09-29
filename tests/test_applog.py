"""modules/applog.py — дописываемый журнал с ограничением размера."""

from modules import applog


def test_write_appends_timestamped_lines(tmp_path):
    p = tmp_path / "x.log"
    applog.write("первая", p)
    applog.write("вторая", p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0].endswith("первая") and lines[1].endswith("вторая")


def test_full_log_moves_aside_and_starts_over(tmp_path, monkeypatch):
    monkeypatch.setattr(applog, "MAX_BYTES", 200)
    p = tmp_path / "x.log"
    for i in range(30):
        applog.write(f"строка номер {i}", p)
    old = tmp_path / "x.log.1"
    assert old.exists()
    assert p.stat().st_size < 400 and old.stat().st_size < 400
    assert "строка номер 29" in p.read_text(encoding="utf-8")


def test_unwritable_target_never_raises(tmp_path):
    applog.write("x", tmp_path / "нет" / "такой" / "папки.log")


def test_service_log_is_rotating():
    import inspect

    from modules import service
    assert "RotatingFileHandler" in inspect.getsource(service.run)
