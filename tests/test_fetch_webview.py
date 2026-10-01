import json

import pytest

from tools import fetch_webview


def test_incomplete_runtime_cannot_be_packaged(tmp_path):
    with pytest.raises(FileNotFoundError, match="Incomplete"):
        fetch_webview.validate(tmp_path)


def test_wrong_pinned_runtime_cannot_be_packaged(tmp_path):
    for name in fetch_webview.REQUIRED:
        (tmp_path / name).write_bytes(b"file")
    (tmp_path / "chimera-runtime.json").write_text(json.dumps({"version": "old"}), encoding="utf-8")
    with pytest.raises(ValueError, match="version mismatch"):
        fetch_webview.validate(tmp_path)
