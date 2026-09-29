"""modules/changelog.py — общий журнал изменений data/changes.log: командная строка и наблюдатель за файлами."""

import re

from modules import changelog


def test_record_appends_tab_separated_line(tmp_path):
    log = tmp_path / "changes.log"

    changelog.record("file", "lists edit youtube", True, log)
    changelog.record("cli", "lists save youtube", False, log)

    first, second = log.read_text(encoding="utf-8").splitlines()
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\tfile\tlists edit youtube\tok", first)
    assert second.endswith("\tcli\tlists save youtube\terror")


def test_record_never_raises_when_log_is_unwritable(tmp_path):
    changelog.record("file", "x", True, tmp_path)  # папка вместо файла: запись невозможна
